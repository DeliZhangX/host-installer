INSTALLER_DIR ?= $(DESTDIR)/opt/xensource/installer
INSTALLER_DATA_DIR ?= $(DESTDIR)/opt/xensource/installer
SUPPORT_DIR ?= $(DESTDIR)/usr/bin

all:

clean:
	rm -rf *.pyc

install:
	mkdir -p $(INSTALLER_DIR) $(SUPPORT_DIR)
	install -m755 clean-installer $(INSTALLER_DIR)
	install -m755 init $(INSTALLER_DIR)
	install -m755 hwdetect $(INSTALLER_DIR)

	install -m755 support.sh $(SUPPORT_DIR)

	install -m644 answerfile_ui.py $(INSTALLER_DIR)
	install -m644 backend.py $(INSTALLER_DIR)
	install -m644 constants.py $(INSTALLER_DIR)
	install -m644 diskutil.py $(INSTALLER_DIR)
	install -m644 generalui.py $(INSTALLER_DIR)
	install -m644 hardware.py $(INSTALLER_DIR)
	install -m644 init_constants.py $(INSTALLER_DIR)
	install -m644 init_simpleui.py $(INSTALLER_DIR)
	install -m644 init_tui.py $(INSTALLER_DIR)
	install -m644 netutil.py $(INSTALLER_DIR)
	install -m644 packaging.py $(INSTALLER_DIR)
	install -m644 pyanswerfile_ui.py $(INSTALLER_DIR)
	install -m644 snackutil.py $(INSTALLER_DIR)
	install -m644 transcribe.py $(INSTALLER_DIR)
	install -m644 tui.py $(INSTALLER_DIR)
	install -m644 uicontroller.py $(INSTALLER_DIR)
	install -m644 util.py $(INSTALLER_DIR)
	install -m644 vm_exporter.py $(INSTALLER_DIR)
	install -m644 xelogging.py $(INSTALLER_DIR)

	install -m644 keymaps $(INSTALLER_DATA_DIR)
	install -m644 timezones $(INSTALLER_DATA_DIR)

	[ ! -e /output/docs/EULA ] || install -m644 /output/docs/EULA $(INSTALLER_DATA_DIR)

