#!/usr/bin/env python
# Copyright (c) 2005-2006 XenSource, Inc. All use and distribution of this 
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by XenSource, Inc. All other rights reserved.
# Xen, XenSource and XenEnterprise are either registered trademarks or 
# trademarks of XenSource Inc. in the United States and/or other countries.

###
# XEN HOST INSTALLER
# Main script
#
# written by Andrew Peace

import sys
import traceback
import time
import os.path
import simplejson as json

# user-interface stuff:
import tui.installer
import tui.installer.screens
import tui.progress
import util
import answerfile
import uicontroller
import constants
import init_constants

# hardware
import disktools
import diskutil
import netutil
import hardware

# backend
import backend
import restore

# general
import repository
import xelogging
import scripts

# fcoe
import fcoeutil

def main(args):
    ui = tui
    xelogging.log("Starting user interface")
    ui.init_ui()
    status = go(ui, args, None, None)
    xelogging.log("Shutting down user interface")
    ui.end_ui()
    return status

def xen_control_domain():
    f = None
    is_xen_control_domain = True

    try:
        f = open("/proc/xen/capabilities",'r')
        lines = [l.strip() for l in f.readlines()]
        is_xen_control_domain = 'control_d' in lines
    except:
        pass
    if f is not None:
        f.close()
    return is_xen_control_domain

# get real path for multipath
def fixMpathResults(results):
    # update primary disk
    primary_disk = None
    if 'primary-disk' in results:
        primary_disk = results['primary-disk']
        master = disktools.getMpathMaster(primary_disk)
        if master:
            primary_disk = master
        results['primary-disk'] = primary_disk

    # update all other disks
    if 'guest-disks' in results:
        disks = []
        for disk in results['guest-disks']:
            master = disktools.getMpathMaster(disk)
            if master:
                # CA-38329: disallow device mapper nodes (except primary disk) as these won't exist
                # at XenServer boot and therefore cannot be added as physical volumes to Local SR.
                # Also, since the DM nodes are multipathed SANs it doesn't make sense to include them
                # in the "Local" SR.
                if master != primary_disk:
                    raise Exception, "Non-local disk %s specified to be added to Local SR" % disk
                disk = master
            disks.append(disk)
        results['guest-disks'] = disks

    return results

def go(ui, args, answerfile_address, answerfile_script):
    extra_repo_defs = []
    results = {
        'keymap': None, 
        'serial-console': None,
        'operation': init_constants.OPERATION_INSTALL,
        'boot-serial': False,
        'extra-repos': [],
        'network-backend': constants.NETWORK_BACKEND_DEFAULT,
        'root-password': ('pwdhash', '!!'),
        }
    suppress_extra_cd_dialog = False
    serial_console = None
    boot_console = None
    boot_serial = False

    if not xen_control_domain() or args.has_key('--virtual'):
        hardware.useVMHardwareFunctions()

    for (opt, val) in args.items():
        if opt == "--boot-console":
            # takes precedence over --console
            if hardware.is_serialConsole(val):
                boot_console = hardware.getSerialConfig()
        elif opt == "--console":
            for console in val:
                if hardware.is_serialConsole(console):
                    serial_console = hardware.getSerialConfig()
            if hardware.is_serialConsole(val[-1]):
                boot_serial = True
        elif opt == "--keymap":
            results["keymap"] = val
            xelogging.log("Keymap specified on command-line: %s" % val)
        elif opt == "--extrarepo":
            extra_repo_defs += val
        elif opt == "--onecd":
            suppress_extra_cd_dialog = True
        elif opt == "--disable-gpt":
            constants.GPT_SUPPORT = False
        elif opt == "--disable-uefi":
            constants.FORCE_LEGACY_BOOT = True

    if boot_console and not serial_console:
        serial_console = boot_console
        boot_serial = True
    if serial_console:
        try:
            results['serial-console'] = hardware.SerialPort.from_string(serial_console)
            results['boot-serial'] = boot_serial
            xelogging.log("Serial console specified on command-line: %s, default boot: %s" % 
                          (serial_console, boot_serial))
        except:
            pass

    interactive = True
    try:
        if os.path.isfile(constants.defaults_data_file):
            data_file = open(constants.defaults_data_file)
            defaults = json.load(data_file)
            results.update(defaults)

        # loading an answerfile?
        assert ui != None or answerfile_address != None or answerfile_script != None

        if answerfile_address and answerfile_script:
            raise RuntimeError, "Both answerfile and answerfile generator passed on command line."

        a = None
        parsing_except = None
        if answerfile_address:
            a = answerfile.Answerfile.fetch(answerfile_address)
        elif answerfile_script:
            a = answerfile.Answerfile.generate(answerfile_script)
        if a:
            interactive = False
            results['network-hardware'] = netutil.scanConfiguration()
            try:
                results.update(a.parseScripts())
                results.update(a.processAnswerfileSetup())

                if results.has_key('extra-repos'):
                    # load drivers now
                    for d in results['extra-repos']:
                        media, address, _ = d
                        for r in repository.repositoriesFromDefinition(media, address):
                            for p in r:
                                if p.type.startswith('driver'):
                                    if p.load() != 0:
                                        raise RuntimeError, "Failed to load driver %s." % p.name

                if 'fcoe-interfaces' in results:
                    fcoeutil.start_fcoe(results['fcoe-interfaces'])

                util.runCmd2(util.udevsettleCmd())
                time.sleep(1)
                diskutil.mpath_part_scan()

                # ensure partitions/disks are not locked by LVM
                lvm = disktools.LVMTool()
                lvm.deactivateAll()
                del lvm

                diskutil.log_available_disks()

                results.update(a.processAnswerfile())
                results = fixMpathResults(results)
            except Exception, e:
                parsing_except = e

        results['extra-repos'] += extra_repo_defs
        xelogging.log("Driver repos: %s" % str(results['extra-repos']))

        scripts.run_scripts('installation-start')

        if parsing_except:
            raise parsing_except

        # log the modules that we loaded:
        xelogging.log("All needed modules should now be loaded. We have loaded:")
        util.runCmd2(["lsmod"])

        status = constants.EXIT_OK

        # how much RAM do we have?
        ram_found_mb = hardware.getHostTotalMemoryKB() / 1024
        ram_warning = ram_found_mb < constants.MIN_SYSTEM_RAM_MB
        vt_warning = not hardware.VTSupportEnabled()

        # Generate the UI sequence and populate some default
        # values in backend input.  Note that not all these screens
        # will be displayed as they have conditional to skip them at
        # the start of each function.  In future these conditionals will
        # be moved into the sequence definition and evaluated by the
        # UI dispatcher.
        aborted = False
        if ui and interactive:
            uiexit = ui.installer.runMainSequence(
                results, ram_warning, vt_warning, suppress_extra_cd_dialog
                )
            if uiexit == uicontroller.EXIT:
                aborted = True

        if not aborted:
            if results['install-type'] == constants.INSTALL_TYPE_RESTORE:
                xelogging.log('INPUT ANSWER DICTIONARY')
                backend.prettyLogAnswers(results)
                xelogging.log("SCRIPTS DICTIONARY:")
                backend.prettyLogAnswers(scripts.script_dict)
                xelogging.log("Starting actual restore")
                backup = results['backup-to-restore']
                if ui:
                    pd = tui.progress.initProgressDialog("Restoring %s" % backup,
                                                         "Restoring data - this may take a while...",
                                                         100)
                def progress(x):
                    if ui and pd:
                        tui.progress.displayProgressDialog(x, pd)
                restore.restoreFromBackup(backup, progress)
                if ui:
                    tui.progress.clearModelessDialog()
                    tui.progress.OKDialog("Restore", "The restore operation completed successfully.")
            else:
                xelogging.log("Starting actual installation")
                results = backend.performInstallation(results, ui, interactive)

                if ui and interactive:
                    ui.installer.screens.installation_complete()
            
                xelogging.log("The installation completed successfully.")
        else:
            xelogging.log("The user aborted the installation from within the user interface.")
            status = constants.EXIT_USER_CANCEL
    except Exception, e:
        try:
            # first thing to do is to get the traceback and log it:
            ex = sys.exc_info()
            err = str.join("", traceback.format_exception(*ex))
            xelogging.log("INSTALL FAILED.")
            xelogging.log("A fatal exception occurred:")
            xelogging.log(err)

            # run the user's scripts - an arg of "1" indicates failure
            scripts.run_scripts('installation-complete', '1')
    
            # collect logs where possible
            xelogging.collectLogs("/tmp")
    
            # now display a friendly error dialog:
            if ui:
                ui.exn_error_dialog("install-log", True, interactive)
            else:
                txt = constants.error_string(str(e), 'install-log', True)
                xelogging.log(txt)
    
            # and now on the disk if possible:
            if 'primary-disk' in results and 'primary-partnum' in results and 'logs-partnum' in results:
                backend.writeLog(results['primary-disk'], results['primary-partnum'], results['logs-partnum'])
            elif 'primary-disk' in results and 'primary-partnum' in results:
                backend.writeLog(results['primary-disk'], results['primary-partnum'], None)
    
            xelogging.log(results)
        except Exception, e:
            # Don't let logging exceptions prevent subsequent actions
            print 'Logging failed: '+str(e)
            
        # exit with failure status:
        status = constants.EXIT_ERROR

    else:
        # run the user's scripts - an arg of "0" indicates success
        try:
            scripts.run_scripts('installation-complete', '0')
        except:
            pass

        # put the log in /tmp:
        xelogging.collectLogs('/tmp')

        # and now on the disk if possible:
        if 'primary-disk' in results and 'primary-partnum' in results and 'logs-partnum' in results:
            backend.writeLog(results['primary-disk'], results['primary-partnum'], results['logs-partnum'])
        elif 'primary-disk' in results and 'primary-partnum' in results:
            backend.writeLog(results['primary-disk'], results['primary-partnum'], None)

        assert (status == constants.EXIT_OK or status == constants.EXIT_USER_CANCEL)
        
    return status

if __name__ == "__main__":
    sys.exit(main(util.splitArgs(sys.argv[1:], array_args = ('--extrarepo'))))
