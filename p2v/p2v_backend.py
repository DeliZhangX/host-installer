# Copyright (c) 2005-2006 XenSource, Inc. All use and distribution of this 
# copyrighted material is governed by and subject to terms and conditions 
# as licensed by XenSource, Inc. All other rights reserved.
# Xen, XenSource and XenEnterprise are either registered trademarks or 
# trademarks of XenSource Inc. in the United States and/or other countries.

###
# XEN CLEAN INSTALLER
# Functions to perform the XE installation
#
# written by Mark Nijmeijer

import os
import os.path
import xml.sax.saxutils

import findroot
import sys
import time
import p2v_constants
import p2v_tui
import p2v_utils
import util
import xelogging
import xmlrpclib

import tui.progress

import urllib
import urllib2
import httpput

ui_package = p2v_tui

from p2v_error import P2VError, P2VPasswordError, P2VMountError, P2VCliError
from version import *

#globals
dropbox_path = "/opt/xensource/packages/xgt/"
local_mount_path = "/tmp/xenpending"

def specifyUI(ui):
    global ui_package
    ui_package = ui

def print_results( results ):
    if p2v_utils.is_debug():
        for key in results.keys():
            sys.stderr.write( "result.key = %s \t\t" % key )
            sys.stderr.write( "result.value = %s\n" % results[key] )

def append_hostname(os_install): 
    os_install[p2v_constants.HOST_NAME] = os.uname()[1]

def determine_size(os_install):
    os_root_device = os_install[p2v_constants.DEV_NAME]
    dev_attrs = os_install[p2v_constants.DEV_ATTRS]
    os_root_mount_point = findroot.mount_os_root( os_root_device, dev_attrs )

    total_size_l = long(0)
    used_size_l = long(0)

    #findroot.determine_size returns in bytes
    (used_size, total_size) = findroot.determine_size(os_root_mount_point, os_root_device )
    
    # adjust total size to 150% of used size, with a minimum of 4Gb
    total_size_l = (long(used_size) * 3) / 2
    if total_size_l < (4 * (1024 ** 3)): # size in template.dat is in bytes
        total_size_l = (4 * (1024 ** 3))
        
    total_size = str(total_size_l)

    #now increase used_size by 100MB, because installing our RPMs during 
    #the p2v process will take up that extra room.
    used_size_l = long(used_size)
    used_size_l += 100 * (1024 ** 2)
    used_size = str(used_size_l)
    
    os_install[p2v_constants.FS_USED_SIZE] = used_size
    os_install[p2v_constants.FS_TOTAL_SIZE] = total_size
    findroot.umount_dev( os_root_mount_point )
    

def check_rw_mount(local_mount_path):
    rc, out = findroot.run_command('touch %s/rwtest' % local_mount_path)
    if rc != 0:
        return rc

    findroot.run_command('rm %s/rwtest' % local_mount_path)
    return 0

def rio_p2v(answers, use_tui = True):
    if use_tui:
        tui.progress.showMessageDialog("Working", "Connecting to server...")

    xapi = xmlrpclib.Server(answers['target-host-name'])
    rc = xapi.session.login_with_password(answers['target-host-user'], 
                                          answers['target-host-password'])
    assert rc['Status'] == 'Success'
    session = rc['Value']

    template_name = "XenSource P2V Server"

    # find and instantiate the P2V server:
    if use_tui:
        tui.progress.clearModelessDialog()
        tui.progress.showMessageDialog("Working", "Provisioning the target virtual machine...")

    xelogging.log("Looking for P2V server template")
    rc = xapi.VM.get_by_name_label(session, template_name)
    if rc['Status'] != 'Success':
        raise RuntimeError, "Unable to get reference to template '%s'" % template_name
    template_refs = rc['Value']
    assert len(template_refs) == 1
    [ template_ref ] = template_refs

    xelogging.log("Cloning a new P2V server")
    rc = xapi.VM.clone(session, template_ref, "New P2Vd guest")
    if rc['Status'] != 'Success':
        raise RuntimeError, "Unable to clone template %s" % template_ref
    guest_ref = rc['Value']

    rc = xapi.VM.set_is_a_template(session, guest_ref, False)
    if rc['Status'] != 'Success':
        raise RuntimeError, "Unable to unset template flag on new guest."

    xelogging.log("Starting P2V server")
    rc = xapi.VM.start(session, guest_ref, False, False)
    if rc['Status'] != 'Success':
        raise RuntimeError, "Unable to start the guest."

    # wait for it to get an IP address:
    p2v_server = None
    xelogging.log("Waiting for P2V server to give us an IP address")
    for i in range(5):
        rc = xapi.VM.get_other_config(session, guest_ref)
        if rc['Status'] != 'Success':
            raise RuntimeError, "Unable to get other config field for ref %s" % guest_ref
        value = rc['Value']
        if value.has_key('ip'):
            p2v_server_ip = value['ip']
            p2v_server = "http://" + p2v_server_ip + ":81"
            break
        else:
            time.sleep(5)

    # need to write some proper error checking code...!:
    assert p2v_server and p2v_server_ip
    xelogging.log("IP address is %s" % p2v_server_ip)

    def p2v_server_call(cmd, args):
        query_string = urllib.urlencode(args)
        address = p2v_server + "/" + cmd + "?" + query_string
        xelogging.log("About to call p2v server: %s" % address)
        r = urllib2.urlopen(address)
        r.close()

    # add a disk, partition it with a big partition, format the partition:
    p2v_server_call('make-disk', {'volume': 'xvda', 'size': str(answers['osinstall'][p2v_constants.FS_TOTAL_SIZE]),
        'sr': answers['target-sr'], 'bootable': 'true'})
    p2v_server_call('partition-disk', {'volume': 'xvda', 'part1': '-1'})
    p2v_server_call('mkfs', {'volume': 'xvda1', 'fs': 'ext3'})
    p2v_server_call('set-fs-metadata', {'volume': 'xvda1', 'mntpoint': '/'})

    # use the old functions for now to make the tarball:
    if use_tui:
        tui.progress.clearModelessDialog()
        tui.progress.showMessageDialog("Working", "Transferring filesystems - this will take a long time...")

    os_root_device = answers['osinstall'][p2v_constants.DEV_NAME]
    dev_attrs = answers['osinstall'][p2v_constants.DEV_ATTRS]
    mntpoint = findroot.mount_os_root(os_root_device, dev_attrs)
    findroot.rio_handle_root(p2v_server_ip, 81, mntpoint, os_root_device)

    if use_tui:
        tui.progress.clearModelessDialog()
        tui.progress.showMessageDialog("Working", "Completing transformation...")

    p2v_server_call('update-fstab', {'root-vol': 'xvda1'})
    p2v_server_call('paravirtualise', {'root-vol': 'xvda1'})
    p2v_server_call('completed', {})

    if use_tui:
        tui.progress.clearModelessDialog()

#stolen from packaging.py
def ejectCD():
    if not os.path.exists("/tmp/cdmnt"):
        os.mkdir("/tmp/cdmnt")

    device = None
    for dev in ['hda', 'hdb', 'hdc', 'scd1', 'scd2',
                'sr0', 'sr1', 'sr2', 'cciss/c0d0p0',
                'cciss/c0d1p0', 'sda', 'sdb']:
        device_path = "/dev/%s" % dev
        if os.path.exists(device_path):
            try:
                util.mount(device_path, '/tmp/cdmnt', ['ro'], 'iso9660')
                if os.path.isfile('/tmp/cdmnt/REVISION'):
                    device = device_path
                    # (leaving the mount there)
                    break
            except util.MountFailureException:
                # clearly it wasn't that device...
                pass
            else:
                if os.path.ismount('/tmp/cdmnt'):
                    util.umount('/tmp/cdmnt')

    if os.path.exists('/usr/bin/eject') and device != None:
        findroot.run_command('/usr/bin/eject %s' % device)
