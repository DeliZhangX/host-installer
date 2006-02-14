#!/usr/bin/python
###
# XEN CLEAN INSTALLER
# Text user interface functions
#
# written by Andrew Peace
# Copyright XenSource Inc. 2006

### TODO: Validation of IP addresses

from snack import *
import generalui
import uicontroller
from version import *

import datetime

screen = None

# functions to start and end the GUI - these create and destroy a snack screen as
# appropriate.
def init_ui(results):
    global screen
    
    screen = SnackScreen()
    screen.drawRootText(0, 0, "Welcome to %s Installer - Version %s" % (PRODUCT_NAME, PRODUCT_VERSION))
    screen.drawRootText(0, 1, "Copyright XenSource, Inc. 2006")
    
def end_ui():
    global screen
    
    if screen:
        screen.finish()
        
def suspend_ui():
    global screen
    if screen:
        screen.suspend()
        
def resume_ui():
    global screen
    if screen:
        screen.resume()

# welcome screen:
def welcome_screen(answers):
    global screen

    ButtonChoiceWindow(screen,
                       "Welcome to %s Setup" % PRODUCT_NAME,
                       """This CD will install %s on your server.

Please ensure that you have backed up any critical data before proceeding, as the installation process will format any disks specified as to be used by %s on this server.""" % (PRODUCT_NAME, PRODUCT_NAME),
                       ['Ok'], width=60)

    # advance to next screen:
    return 1

# select drive to use as the Dom0 disk:
def select_primary_disk(answers):
    global screen

    entries = generalui.getDiskList()

    (button, entry) = ListboxChoiceWindow(screen,
                        "Select Primary Disk",
                        """Please select the disk you would like to use as the primary %s disk.

Xen will be installed onto this disk, requiring 120MB, and the remaining space used for guest virtual machines.""" % PRODUCT_NAME,
                        entries,
                        ['Ok', 'Back'])

    answers['primary-disk'] = entries[entry]

    if button == "ok" or button == None: return 1
    if button == "back": return -1

def select_guest_disks(answers):
    global screen

    entries = generalui.getDiskList()
    entries.remove(answers['primary-disk'])

    text = TextboxReflowed(50, "Please select any additional disks you would like to use for guest storage")
    buttons = ButtonBar(screen, [('Ok', 'ok'), ('Back', 'back')])
    cbt = CheckboxTree(4, 1)
    for x in entries:
        cbt.append(x)
    
    gf = GridFormHelp(screen, 'Select Additional Disks', None, 1, 3)
    gf.add(text, 0, 0, padding = (0, 0, 0, 1))
    gf.add(cbt, 0, 1, padding = (0, 0, 0, 1))
    gf.add(buttons, 0, 2)
    
    result = gf.runOnce()

    answers['guest-disks'] = cbt.getSelection()

    if buttons.buttonPressed(result) == 'ok': return 1
    if buttons.buttonPressed(result) == 'back': return -1

# confirm they want to blow stuff away:
def confirm_installation_multiple_disks(answers):
    global screen

    disks = [ answers['primary-disk'] ] + answers['guest-disks']
    disks_used = generalui.makeHumanList(disks)

    button = ButtonChoiceWindow(screen,
                                "Confirm Installation",
                                """We have collected all the information required to install %s.

If you proceed, ALL DATA WILL BE DESTROYED on the disks selected for use by %s (you selected %s)""" % (PRODUCT_NAME, PRODUCT_NAME, disks_used),
                                ['Ok', 'Back'])

    if button == "ok": return 1
    if button == "back": return -1

def confirm_installation_one_disk(answers):
    global screen

    button = ButtonChoiceWindow(screen,
                                "Confirm Installation",
                                """Since your server only has a single disk, this will be used to install %s.

Please confirm you wish to proceed; all data on this disk will be destroyed (vendor service partitions will be left intact)""" % PRODUCT_NAME,
                                ['Ok', 'Back'])

    if button == "ok": return 1
    if button == "back": return -1

def get_root_password(answers):
    global screen
    done = False
    
    while not done:
        (button, result) = PasswordEntryWindow(screen,
                                     "Set Password",
                                     "Please specify the admin password for this installation",
                                     ['Password', 'Confirm'],
                                     buttons = ['Ok', 'Back'])
        if button == 'back':
            return -1
        
        (pw, conf) = result[1]
        if pw == conf:
            if pw == None or len(pw) == 0:
                ButtonChoiceWindow(screen,
                               "Password Error",
                               "Please enter a non-empty password.",
                               ['Ok'])
            else:
                done = True
        else:
            ButtonChoiceWindow(screen,
                               "Password Error",
                               "The passwords you entered did not match.  Please try again.",
                               ['Ok'])

    # if they didn't select OK we should have returned already
    assert button == 'ok'
    answers['root-password'] = pw
    return 1

def determine_basic_network_config(answers):
    global screen

    entries = [ 'Configure all interfaces using DHCP',
                'Specify a different network configuration' ]

    (button, entry) = ListboxChoiceWindow(screen,
                                          "Network Configuration",
                                          "How would you like networking to be configured on this host?",
                                          entries,
                                          ['Ok', 'Back'])

    if button == "ok" or button == None:
        # proceed to get_autoconfig_ifaces if manual configuration was selected:
        if entry == 1:
            seq = [ get_autoconfig_ifaces ]
            rv = uicontroller.runUISequence(seq, answers)
            if rv == -1: return 0
            if rv == 1: return 1
        else:
            answers['iface-configuration'] = (True, None)
            return 1
    
    if button == "back": return -1


def get_autoconfig_ifaces(answers):
    global screen

    entries = generalui.getNetifList()

    text = TextboxReflowed(50, "Which network interfaces need to be configured manually?")
    buttons = ButtonBar(screen, [('Ok', 'ok'), ('Back', 'back')])
    cbt = CheckboxTree(4, 1)
    for x in entries:
        cbt.append(x)
    
    gf = GridFormHelp(screen, 'Network Configuration', None, 1, 3)
    gf.add(text, 0, 0, padding = (0, 0, 0, 1))
    gf.add(cbt, 0, 1, padding = (0, 0, 0, 1))
    gf.add(buttons, 0, 2)
    
    result = gf.runOnce()

    if buttons.buttonPressed(result) == 'back': return -1

    seq = []
    manually_configured = cbt.getSelection()

    for x in manually_configured:
        seq.append((get_iface_configuration, { 'iface': x }))

    if len(seq) == 0:
        answers['iface-configuration']  = (True, None)
        if buttons.buttonPressed(result) == 'back': return -1
        if buttons.buttonPressed(result) == 'ok': return 1

    subdict = {}

    rv = uicontroller.runUISequence(seq, subdict)

    for x in entries:
        if x not in manually_configured:
            subdict[x] = {"use-dhcp": True}

    answers['iface-configuration'] = (False, subdict)
    
    if rv == -1: return 0
    if rv == 1: return 1
    

def get_iface_configuration(answers, args):
    global screen

    iface = args['iface']

    (button, (ip, snm, gw)) = EntryWindow(screen,
                                          "Configuration for %s" % iface,
                                          "Please give configuration details for the interface %s" % iface,
                                          ['IP Address:', 'Subnet mask:', 'Gateway:'],
                                          buttons = ['Ok', 'Back'])

    answers[iface] = {'use-dhcp': False,
                      'ip': ip,
                      'subnet-mask': snm,
                      'gateway': gw }
    
    if button == 'ok': return 1
    if button == 'back': return -1

def get_nameservers(answers):
    global screen

    (button, (ns1, ns2, ns3)) = EntryWindow(screen,
                                            "Nameservers",
                                            "Enter the hostnames or IP addresses of DNS hosts to be used for name resolution",
                                            ['Nameserver 1', 'Nameserver 2', 'Nameserver 3'],
                                            ['Ok', 'Back'])

    answers['nameservers'] = [ ns1, ns2, ns3 ]

    if button == "ok": return 1
    if button == 'back': return -1

def need_manual_hostname(answers):
    global screen

    button = ButtonChoiceWindow(screen,
                                "Hostname",
                                "Do you need to manually specify a hostname for this server?",
                                ['No', 'Yes', 'Back'])

    if button == "yes":
        result = EntryWindow(screen,
                             "Hostname",
                             "Enter the hostname you would like to use for this server:",
                             ['Hostname'],
                             buttons = ['Ok', 'Back'])
        if result[0] == 'ok':
            (hn) = result[1]
            rv = 1
            answers['manual-hostname'] = (True, hn)
        else:
            rv = 0
    elif button == "no":
        rv = 1
        answers['manual-hostname'] = (False, None)
    else:
        rv = -1

    return rv

def get_timezone(answers):
    global screen

    entries = generalui.getTimeZones()

    (button, entry) = ListboxChoiceWindow(screen,
                                          "Select Timezone",
                                          "Which timezone is the managed host in?",
                                          entries,
                                          ['Ok', 'Back'], height = 8, scroll = 1)

    if button == "ok" or button == None:
        answers['timezone'] = entries[entry]
        return 1
    
    if button == "back": return -1

def set_time(answers):
    global screen

    now = datetime.datetime.now()

    result = EntryWindow(screen,
                         "Set local time",
                         "Please enter the current date and time",
                         [('Day (DD)', Entry(3, str(now.day))),
                          ('Month (MM)', Entry(3, str(now.month))),
                          ('Year (YYYY)', Entry(5, str(now.year))),
                          ('Hour (0-23)', Entry(3, str(now.hour))),
                          ('Minute (0-59)', Entry(3, str(now.minute)))],
                         buttons = ['Ok', 'Back'])

    (button, (day, month, year, hour, minute)) = result

    if button == 'ok':
        answers['set-time-dialog-dismissed'] = datetime.datetime.now()
        answers['localtime'] = datetime.datetime(int(year),
                                                 int(month),
                                                 int(day),
                                                 int(hour),
                                                 int(minute))
        return 1
    if button == 'back': return -1

def installation_complete(answers):
    global screen

    ButtonChoiceWindow(screen,
                       "Installation Complete",
                       """The %s installation has completed.  Please press enter to reboot the machine.
                       
The CD will automatically eject upon reboot""" % PRODUCT_NAME,
                       ['Ok'])

    return 1
                      


###
# Helper functions
def PasswordEntryWindow(screen, title, text, prompts, allowCancel = 1, width = 40,
                        entryWidth = 20, buttons = [ 'Ok', 'Cancel' ], help = None):
    bb = ButtonBar(screen, buttons);
    t = TextboxReflowed(width, text)

    count = 0
    for n in prompts:
        count = count + 1

    sg = Grid(2, count)

    count = 0
    entryList = []
    for n in prompts:
        if (type(n) == types.TupleType):
            (n, e) = n
        else:
            e = Entry(entryWidth, password = 1)

        sg.setField(Label(n), 0, count, padding = (0, 0, 1, 0), anchorLeft = 1)
        sg.setField(e, 1, count, anchorLeft = 1)
        count = count + 1
        entryList.append(e)

    g = GridFormHelp(screen, title, help, 1, 3)

    g.add(t, 0, 0, padding = (0, 0, 0, 1)) 
    g.add(sg, 0, 1, padding = (0, 0, 0, 1))
    g.add(bb, 0, 2, growx = 1)

    result = g.runOnce()

    entryValues = []
    count = 0
    for n in prompts:
        entryValues.append(entryList[count].value())
        count = count + 1

    return (bb.buttonPressed(result), tuple(entryValues))

###
# Progress dialog:
def initProgressDialog(title, text, total):
    global screen
    
    form = GridFormHelp(screen, title, None, 1, 3)
    
    t = Textbox(60, 1, text)
    scale = Scale(60, total)
    form.add(t, 0, 0, padding = (0,0,0,1))
    form.add(scale, 0, 1, padding = (0,0,0,0))

    return (form, scale)

def displayProgressDialog(current, (form, scale)):
    global screen
    
    scale.set(current)

    form.draw()
    screen.refresh()

def displayInfoDialog(title, text):
    global screen

    form = GridFormHelp(screen, title, None, 1, 2)
    
    t = TextboxReflowed(60, text)
    form.add(t, 0, 0)
    form.draw()
    screen.refresh()

def clearModelessDialog():
    global screen
    
    screen.popWindow()
