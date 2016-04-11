#!python
#
# This file is part of https://github.com/zsquareplusc/python-embedded-launcher
# (C) 2016 Chris Liechti <cliechti@gmx.net>
#
# SPDX-License-Identifier:    BSD-3-Clause
"""\
A distutils/setuptools command extension, so that building applications is as
easy as "python setup.py bdist_launcher".
"""

import distutils.cmd
from distutils import log
import sys
import os
import pkgutil
import zipfile

import launcher_tool.copy_launcher
import launcher_tool.launcher_zip
import launcher_tool.resource_editor
import launcher_tool.create_python27_minimal
import launcher_tool.download_python3_minimal
from launcher_tool.download_python3_minimal import URL_32, URL_64


class bdist_launcher(distutils.cmd.Command):
    """\
    Additional command for distutils/setuptools.
    """
    #pylint: disable=invalid-name,attribute-defined-outside-init

    description = "Build windows executables"

    user_options = [
        ('icon=', None, 'filename of icon to use'),
        ('python-minimal=', None, 'change the location of the python-minimal location'),
        ('extend-sys-path=', 'p', 'add search pattern(s) for files added to '
                                  'sys.path (separated by "{}")'.format(os.pathsep)),
        ('wait-at-exit', None, 'do not close console window automatically'),
        ('wait-on-error', None, 'wait if there is an exception'),
    ]

    boolean_options = ['wait-at-exit', 'wait-on-error']


    def initialize_options(self):
        self.icon = None
        self.python_minimal = None
        self.extend_sys_path = None
        self.wait_at_exit = False
        self.wait_on_error = False

    def finalize_options(self):
        self.use_python27 = (sys.version_info.major == 2)
        self.is_64bits = sys.maxsize > 2**32  # recommended by docs.python.org "platform" module
        if self.extend_sys_path is None:
            self.extend_sys_path = ()
        else:
            self.extend_sys_path = self.extend_sys_path.split(os.pathsep)
        self.dest_dir = os.path.join('dist', 'launcher{}-{}'.format(
            '27' if self.use_python27 else '3',
            '64' if self.is_64bits else '32'))

    def copy_customized_launcher(self, fileobj):
        """\
        Copy launcher to build dir and run the resource editor, output result
        to given fileobj.
        """
        build_dir = os.path.join('build', 'bdist_launcher.{}.{}'.format(
            '27' if self.use_python27 else '3',
            '64' if self.is_64bits else '32'))
        self.mkpath(build_dir)
        launcher_temp = os.path.join(build_dir, 'launcher.exe')
        with open(launcher_temp, 'wb') as temp_exe:
            launcher_tool.copy_launcher.copy_launcher(temp_exe, self.use_python27, self.is_64bits)
        if self.icon is not None:
            log.info('changing icon to: {}'.format(self.icon))
            ico = launcher_tool.resource_editor.icon.Icon()
            ico.load(self.icon)
            with launcher_tool.resource_editor.ResourceEditor(launcher_temp) as res:
                ico.save_as_resource(res, 1, 1033)
        if self.python_minimal is not None:
            log.info('changing path to python-minimal to: {}'.format(self.python_minimal))
            with launcher_tool.resource_editor.ResourceReader(launcher_temp) as res:
                string_table = res.get_string_table()
            string_table.languages[1033][1] = self.python_minimal
            with launcher_tool.resource_editor.ResourceEditor(launcher_temp) as res:
                string_table.save_to_resource(res)
        with open(launcher_temp, 'rb') as temp_exe:
            fileobj.write(temp_exe.read())

    def write_launcher(self, filename, main_script):
        """\
        helper function that writes a launcher exe with the appended __main__.py
        and support files
        """
        with open(filename, 'wb') as exe:
            if self.icon is None and self.python_minimal is None:
                launcher_tool.copy_launcher.copy_launcher(exe, self.use_python27, self.is_64bits)
            else:
                self.copy_customized_launcher(exe)
            with zipfile.ZipFile(exe, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('__main__.py', main_script.encode('utf-8'))
                archive.writestr('launcher.py', pkgutil.get_data('launcher_tool', 'launcher.py'))

    def process_entry_point(self, entry_point_name):
        if entry_point_name in self.distribution.entry_points and self.distribution.entry_points[entry_point_name]:
            #~ print(self.distribution.entry_points[entry_point_name])
            for combination in self.distribution.entry_points[entry_point_name]:
                name, entry_point = combination.split('=')
                name = name.strip()
                entry_point = entry_point.strip()
                filename = os.path.join(self.dest_dir, '{}.exe'.format(name))
                main_script = launcher_tool.launcher_zip.make_main(
                    entry_point=entry_point,
                    extend_sys_path=self.extend_sys_path,
                    wait_at_exit=self.wait_at_exit,
                    wait_on_error=self.wait_on_error)
                self.execute(self.write_launcher,
                             (filename, main_script),
                             'writing launcher {}'.format(filename))

    def process_scripts(self):
        for source in self.distribution.scripts:
            filename = os.path.join(self.dest_dir, '{}.exe'.format(os.path.basename(source)))
            script = open(source).read()
            # append users' script to the launcher boot code
            main_script = '{}\n{}'.format(launcher_tool.launcher_zip.make_main(
                extend_sys_path=self.extend_sys_path,
                wait_at_exit=self.wait_at_exit,
                wait_on_error=self.wait_on_error), script)
            self.execute(self.write_launcher,
                         (filename, main_script),
                         'writing launcher {}'.format(filename))

    def run(self):
        #~ print(dir(self.distribution))
        #~ print(self.distribution.scripts)
        #~ print(self.distribution.requires)

        log.info('installing to {}'.format(self.dest_dir))
        self.mkpath(self.dest_dir)

        log.info('preparing a wheel file of application')
        self.run_command('bdist_wheel')
        log.info('installing wheel of application (with dependencies)')
        self.spawn([sys.executable, '-m', 'pip', 'install',
                    '--disable-pip-version-check',
                    '--prefix', self.dest_dir,
                    '--ignore-installed',  # '--no-index',
                    '--find-links=dist', self.distribution.get_name()])

        if hasattr(self.distribution, 'entry_points') and self.distribution.entry_points:
            self.process_entry_point('console_scripts')
            self.process_entry_point('gui_scripts')

        if hasattr(self.distribution, 'scripts') and self.distribution.scripts:
            self.process_scripts()

        if self.python_minimal is None:
            if self.use_python27:
                if not os.path.exists(os.path.join(self.dest_dir, 'python27-minimal')):
                    launcher_tool.create_python27_minimal.copy_python(
                        os.path.join(self.dest_dir, 'python27-minimal'))
                else:
                    log.info('python27-minimal installation already present')
            else:
                if not os.path.exists(os.path.join(self.dest_dir, 'python3-minimal')):
                    log.info('extracting python minimal installation')
                    launcher_tool.download_python3_minimal.extract(
                        URL_64 if self.is_64bits else URL_32,
                        os.path.join(self.dest_dir, 'python3-minimal'))
                else:
                    log.info('python3-minimal installation already present')