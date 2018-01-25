import os
from pkg_resources import parse_version
import re
import tempfile
import shutil
import json
import pytest
import warnings
from pipenv.cli import activate_virtualenv
from pipenv.utils import (
    temp_environ, get_windows_path, mkdir_p, normalize_drive, rmtree, TemporaryDirectory
)
from pipenv.vendor import toml
from pipenv.vendor import delegator
from pipenv.project import Project
from pipenv.vendor.six import PY2
if PY2:
    class ResourceWarning(Warning):
        pass

try:
    from pathlib import Path
except:
    from pipenv.vendor.pathlib2 import Path

os.environ['PIPENV_DONT_USE_PYENV'] = '1'
os.environ['PIPENV_IGNORE_VIRTUALENVS'] = '1'


@pytest.fixture(scope='class')
def pip_src_dir(request):
    old_src_dir = os.environ.get('PIP_SRC', '')
    new_src_dir = TemporaryDirectory(prefix='pipenv-', suffix='-testsrc')
    os.environ['PIP_SRC'] = new_src_dir.name
    def finalize():
        new_src_dir.cleanup()
        os.environ['PIP_SRC'] = old_src_dir
    request.addfinalizer(finalize)
    return request


class PipenvInstance():
    """An instance of a Pipenv Project..."""
    def __init__(self, pipfile=True, chdir=False):
        self.original_umask = os.umask(0o007)
        self.original_dir = os.path.abspath(os.curdir)
        self._path = TemporaryDirectory(suffix='project', prefix='pipenv')
        self.path = self._path.name
        # set file creation perms
        self.pipfile_path = None
        self.chdir = chdir

        if pipfile:
            p_path = os.sep.join([self.path, 'Pipfile'])
            with open(p_path, 'a'):
                os.utime(p_path, None)

            self.chdir = False or chdir
            self.pipfile_path = p_path

    def __enter__(self):
        if self.chdir:
            os.chdir(self.path)
        return self

    def __exit__(self, *args):
        warn_msg = 'Failed to remove resource: {!r}'
        if self.chdir:
            os.chdir(self.original_dir)
        self.path = None
        try:
            self._path.cleanup()
        except OSError as e:
            _warn_msg = warn_msg.format(e)
            warnings.warn(_warn_msg, ResourceWarning)
        finally:
            os.umask(self.original_umask)

    def pipenv(self, cmd, block=True):
        if self.pipfile_path:
            os.environ['PIPENV_PIPFILE'] = self.pipfile_path

        c = delegator.run('pipenv {0}'.format(cmd), block=block)

        if 'PIPENV_PIPFILE' in os.environ:
            del os.environ['PIPENV_PIPFILE']

        # Pretty output for failing tests.
        if block:
            print('$ pipenv {0}'.format(cmd))
            print(c.out)
            print(c.err)

        # Where the action happens.
        return c

    @property
    def pipfile(self):
        p_path = os.sep.join([self.path, 'Pipfile'])
        with open(p_path, 'r') as f:
            return toml.loads(f.read())

    @property
    def lockfile(self):
        p_path = os.sep.join([self.path, 'Pipfile.lock'])
        with open(p_path, 'r') as f:
            return json.loads(f.read())


class TestPipenv:
    """The ultimate testing class."""

    @pytest.mark.cli
    def test_pipenv_where(self):
        with PipenvInstance() as p:
            assert normalize_drive(p.path) in p.pipenv('--where').out

    @pytest.mark.cli
    def test_pipenv_venv(self):
        with PipenvInstance() as p:
            p.pipenv('--python python')
            assert p.pipenv('--venv').out

    @pytest.mark.cli
    def test_pipenv_py(self):
        with PipenvInstance() as p:
            p.pipenv('--python python')
            assert p.pipenv('--py').out

    @pytest.mark.cli
    def test_pipenv_rm(self):
        with PipenvInstance() as p:
            p.pipenv('--python python')
            venv_path = p.pipenv('--venv').out

            assert p.pipenv('--rm').out
            assert not os.path.isdir(venv_path)

    @pytest.mark.cli
    def test_pipenv_graph(self):
        with PipenvInstance() as p:
            p.pipenv('install requests')
            assert 'requests' in p.pipenv('graph').out
            assert 'requests' in p.pipenv('graph --json').out

    @pytest.mark.cli
    def test_pipenv_graph_reverse(self):
        with PipenvInstance() as p:
            p.pipenv('install requests==2.18.4')
            output = p.pipenv('graph --reverse').out

            requests_dependency = [
                ('certifi', 'certifi>=2017.4.17'),
                ('chardet', 'chardet(>=3.0.2,<3.1.0|<3.1.0,>=3.0.2)'),
                ('idna', 'idna(>=2.5,<2.7|<2.7,>=2.5)'),
                ('urllib3', 'urllib3(>=1.21.1,<1.23|<1.23,>=1.21.1)')
            ]

            for dep_name, dep_constraint in requests_dependency:
                dep_match = re.search(r'^{}==[\d.]+$'.format(dep_name), output, flags=re.MULTILINE)
                dep_requests_match = re.search(r'^  - requests==2.18.4 \[requires: {}\]$'.format(dep_constraint), output, flags=re.MULTILINE)
                assert dep_match is not None
                assert dep_requests_match is not None
                assert dep_requests_match.start() > dep_match.start()

            c = p.pipenv('graph --reverse --json')
            assert c.return_code == 1
            assert 'Warning: Using both --reverse and --json together is not supported.' in c.err

    @pytest.mark.cli
    def test_pipenv_check(self):
        with PipenvInstance() as p:
            p.pipenv('install requests==1.0.0')
            assert 'requests' in p.pipenv('check').out

    @pytest.mark.cli
    def test_venv_envs(self):
        with PipenvInstance() as p:
            assert p.pipenv('--envs').out

    @pytest.mark.cli
    def test_venv_jumbotron(self):
        with PipenvInstance() as p:
            assert p.pipenv('--jumbotron').out

    @pytest.mark.cli
    def test_bare_output(self):
        with PipenvInstance() as p:
            assert p.pipenv('').out

    @pytest.mark.cli
    def test_help(self):
        with PipenvInstance() as p:
            assert p.pipenv('--help').out

    @pytest.mark.cli
    def test_completion(self):
        with PipenvInstance() as p:
            assert p.pipenv('--completion').out

    @pytest.mark.cli
    def test_man(self):
        with PipenvInstance() as p:
            c = p.pipenv('--man')
            assert c.return_code == 0 or c.err

    @pytest.mark.cli
    @pytest.mark.install
    def test_install_parse_error(self):
        with PipenvInstance() as p:
            # Make sure unparseable packages don't wind up in the pipfile
            # Escape $ for shell input
            c = p.pipenv('install tablib u/\\/p@r\$34b13+pkg')
            assert c.return_code != 0
            assert 'u/\\/p@r$34b13+pkg' not in p.pipfile['packages']

    @pytest.mark.install
    @pytest.mark.setup
    @pytest.mark.skip(reason="this doesn't work on travis")
    def test_basic_setup(self):
        with PipenvInstance() as p:
            with PipenvInstance(pipfile=False) as p:
                c = p.pipenv('install requests')
                assert c.return_code == 0

                assert 'requests' in p.pipfile['packages']
                assert 'requests' in p.lockfile['default']
                assert 'chardet' in p.lockfile['default']
                assert 'idna' in p.lockfile['default']
                assert 'urllib3' in p.lockfile['default']
                assert 'certifi' in p.lockfile['default']

    @pytest.mark.spelling
    @pytest.mark.skip(reason="this is slightly non-deterministic")
    def test_spell_checking(self):
        with PipenvInstance() as p:
            c = p.pipenv('install flaskcors', block=False)
            c.expect(u'[Y//n]:')
            c.send('y')
            c.block()

            assert c.return_code == 0
            assert 'flask-cors' in p.pipfile['packages']
            assert 'flask' in p.lockfile['default']

    @pytest.mark.install
    def test_basic_install(self):
        with PipenvInstance() as p:
            c = p.pipenv('install requests')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'requests' in p.lockfile['default']
            assert 'chardet' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']

    @pytest.mark.dev
    @pytest.mark.run
    @pytest.mark.install
    def test_basic_dev_install(self):
        with PipenvInstance() as p:
            c = p.pipenv('install requests --dev')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['dev-packages']
            assert 'requests' in p.lockfile['develop']
            assert 'chardet' in p.lockfile['develop']
            assert 'idna' in p.lockfile['develop']
            assert 'urllib3' in p.lockfile['develop']
            assert 'certifi' in p.lockfile['develop']

            c = p.pipenv('run python -m requests.help')
            assert c.return_code == 0

    @pytest.mark.dev
    @pytest.mark.install
    def test_install_without_dev(self):
        """Ensure that running `pipenv install` doesn't install dev packages"""
        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
tablib = "*"

[dev-packages]
records = "*"
                """.strip()
                f.write(contents)
            c = p.pipenv('install')
            assert c.return_code == 0
            assert 'tablib' in p.pipfile['packages']
            assert 'records' in p.pipfile['dev-packages']
            assert 'tablib' in p.lockfile['default']
            assert 'records' in p.lockfile['develop']
            c = p.pipenv('run python -c "import records"')
            assert c.return_code != 0
            c = p.pipenv('run python -c "import tablib"')
            assert c.return_code == 0
                

    @pytest.mark.run
    @pytest.mark.uninstall
    def test_uninstall(self):
        with PipenvInstance() as p:
            c = p.pipenv('install requests')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'requests' in p.lockfile['default']
            assert 'chardet' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']

            c = p.pipenv('uninstall requests')
            assert c.return_code == 0
            assert 'requests' not in p.pipfile['dev-packages']
            assert 'requests' not in p.lockfile['develop']
            assert 'chardet' not in p.lockfile['develop']
            assert 'idna' not in p.lockfile['develop']
            assert 'urllib3' not in p.lockfile['develop']
            assert 'certifi' not in p.lockfile['develop']

            c = p.pipenv('run python -m requests.help')
            assert c.return_code > 0

    @pytest.mark.files
    @pytest.mark.run
    @pytest.mark.uninstall
    def test_uninstall_all_local_files(self):
        file_name = 'tablib-0.12.1.tar.gz'
        # Not sure where travis/appveyor run tests from
        test_dir = os.path.dirname(os.path.abspath(__file__))
        source_path = os.path.abspath(os.path.join(test_dir, 'test_artifacts', file_name))

        with PipenvInstance() as p:
            shutil.copy(source_path, os.path.join(p.path, file_name))
            os.mkdir(os.path.join(p.path, "tablib"))
            c = p.pipenv('install {}'.format(file_name))
            c = p.pipenv('uninstall --all --verbose')
            assert c.return_code == 0
            assert 'tablib' in c.out
            assert 'tablib' not in p.pipfile['packages']

    @pytest.mark.run
    @pytest.mark.uninstall
    def test_uninstall_all_dev(self):
        with PipenvInstance() as p:
            c = p.pipenv('install --dev requests pytest')
            assert c.return_code == 0
            
            c = p.pipenv('install tpfd')
            assert c.return_code == 0
            
            assert 'tpfd' in p.pipfile['packages']
            assert 'requests' in p.pipfile['dev-packages']
            assert 'pytest' in p.pipfile['dev-packages']
            assert 'tpfd' in p.lockfile['default']
            assert 'requests' in p.lockfile['develop']
            assert 'pytest' in p.lockfile['develop']


            c = p.pipenv('uninstall --all-dev')
            assert c.return_code == 0
            assert 'requests' not in p.pipfile['dev-packages']
            assert 'pytest' not in p.pipfile['dev-packages']
            assert 'requests' not in p.lockfile['develop']
            assert 'pytest' not in p.lockfile['develop']
            assert 'tpfd' in p.pipfile['packages']
            assert 'tpfd' in p.lockfile['default']


            c = p.pipenv('run python -m requests.help')
            assert c.return_code > 0
            
            c = p.pipenv('run python -c "import tpfd"')
            assert c.return_code == 0

    @pytest.mark.extras
    @pytest.mark.install
    def test_extras_install(self):
        with PipenvInstance() as p:
            c = p.pipenv('install requests[socks]')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'extras' in p.pipfile['packages']['requests']

            assert 'requests' in p.lockfile['default']
            assert 'chardet' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'pysocks' in p.lockfile['default']

    @pytest.mark.extras
    @pytest.mark.install
    @pytest.mark.local
    def test_local_extras_install(self):
        with PipenvInstance() as p:
            setup_py = os.path.join(p.path, 'setup.py')
            with open(setup_py, 'w') as fh:
                contents = """
from setuptools import setup, find_packages

setup(
    name='test_pipenv',
    version='0.1',
    description='Pipenv Test Package',
    author='Pipenv Test',
    author_email='test@pipenv.package',
    license='PIPENV',
    packages=find_packages(),
    install_requires=['tablib'],
    extras_require={'dev': ['flake8', 'pylint']},
    zip_safe=False
)
                """.strip()
                fh.write(contents)
            c = p.pipenv('install .[dev]')
            assert c.return_code == 0
            key = [k for k in p.pipfile['packages'].keys()][0]
            dep = p.pipfile['packages'][key]
            assert dep['path'] == '.'
            assert dep['extras'] == ['dev']
            assert key in p.lockfile['default']
            assert 'dev' in p.lockfile['default'][key]['extras']

    @pytest.mark.vcs
    @pytest.mark.install
    def test_basic_vcs_install(self):
        with PipenvInstance() as p:
            c = p.pipenv('install git+https://github.com/requests/requests.git#egg=requests')
            assert c.return_code == 0
            # edge case where normal package starts with VCS name shouldn't be flagged as vcs
            c = p.pipenv('install gitdb2')
            assert c.return_code == 0
            assert all(package in p.pipfile['packages'] for package in ['requests', 'gitdb2'])
            assert 'git' in p.pipfile['packages']['requests']
            assert p.lockfile['default']['requests'] == {"git": "https://github.com/requests/requests.git"}
            assert 'gitdb2' in p.lockfile['default']

    @pytest.mark.e
    @pytest.mark.vcs
    @pytest.mark.install
    def test_editable_vcs_install(self, pip_src_dir):
        with PipenvInstance() as p:
            c = p.pipenv('install -e git+https://github.com/requests/requests.git#egg=requests')
            assert c.return_code == 0
            assert 'requests' in p.pipfile['packages']
            assert 'git' in p.pipfile['packages']['requests']
            assert 'editable' in p.pipfile['packages']['requests']
            assert 'editable' in p.lockfile['default']['requests']
            assert 'chardet' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']

    @pytest.mark.install
    @pytest.mark.pin
    def test_windows_pinned_pipfile(self):
        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
tablib = "<0.12"
                """.strip()
                f.write(contents)
            c = p.pipenv('install')
            assert c.return_code == 0
            assert 'tablib' in p.pipfile['packages']
            assert 'tablib' in p.lockfile['default']


    @pytest.mark.e
    @pytest.mark.install
    @pytest.mark.vcs
    @pytest.mark.resolver
    def test_editable_vcs_install_in_pipfile_with_dependency_resolution_doesnt_traceback(self):
        # See https://github.com/pypa/pipenv/issues/1240
        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
pypa-docs-theme = {git = "https://github.com/pypa/pypa-docs-theme", editable = true}

# This version of requests depends on idna<2.6, forcing dependency resolution
# failure
requests = "==2.16.0"
idna = "==2.6.0"
                """.strip()
                f.write(contents)
            c = p.pipenv('install')
            assert c.return_code == 1
            assert "Your dependencies could not be resolved" in c.err
            assert 'Traceback' not in c.err


    @pytest.mark.run
    @pytest.mark.install
    def test_multiprocess_bug_and_install(self):
        with temp_environ():
            os.environ['PIPENV_MAX_SUBPROCESS'] = '2'

            with PipenvInstance() as p:
                with open(p.pipfile_path, 'w') as f:
                    contents = """
[packages]
requests = "*"
records = "*"
tpfd = "*"
                    """.strip()
                    f.write(contents)

                c = p.pipenv('install')
                assert c.return_code == 0

                assert 'requests' in p.lockfile['default']
                assert 'idna' in p.lockfile['default']
                assert 'urllib3' in p.lockfile['default']
                assert 'certifi' in p.lockfile['default']
                assert 'records' in p.lockfile['default']
                assert 'tpfd' in p.lockfile['default']
                assert 'parse' in p.lockfile['default']

                c = p.pipenv('run python -c "import requests; import idna; import certifi; import records; import tpfd; import parse;"')
                assert c.return_code == 0

    @pytest.mark.sequential
    @pytest.mark.install
    def test_sequential_mode(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "*"
records = "*"
tpfd = "*"
                """.strip()
                f.write(contents)

            c = p.pipenv('install --sequential')
            assert c.return_code == 0

            assert 'requests' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']
            assert 'records' in p.lockfile['default']
            assert 'tpfd' in p.lockfile['default']
            assert 'parse' in p.lockfile['default']

            c = p.pipenv('run python -c "import requests; import idna; import certifi; import records; import tpfd; import parse;"')
            assert c.return_code == 0

    @pytest.mark.install
    @pytest.mark.resolver
    @pytest.mark.backup_resolver
    def test_backup_resolver(self):
        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
"ibm-db-sa-py3" = "==0.3.1-1"
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0
            assert 'ibm-db-sa-py3' in p.lockfile['default']


    @pytest.mark.sequential
    @pytest.mark.install
    @pytest.mark.update
    def test_sequential_update_mode(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "*"
records = "*"
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0

            assert 'requests' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']
            assert 'records' in p.lockfile['default']

            c = p.pipenv('run python -c "import requests; import idna; import certifi; import records;"')
            assert c.return_code == 0

            c = p.pipenv('update --sequential')
            assert c.return_code == 0

            assert 'requests' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']
            assert 'records' in p.lockfile['default']

            c = p.pipenv('run python -c "import requests; import idna; import certifi; import records;"')
            assert c.return_code == 0

    @pytest.mark.run
    @pytest.mark.markers
    @pytest.mark.install
    def test_package_environment_markers(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = {version = "*", markers="os_name=='splashwear'"}
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0

            assert 'Ignoring' in c.out
            assert 'markers' in p.lockfile['default']['requests']

            c = p.pipenv('run python -c "import requests;"')
            assert c.return_code == 1

    @pytest.mark.run
    @pytest.mark.alt
    @pytest.mark.install
    def test_specific_package_environment_markers(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = {version = "*", os_name = "== 'splashwear'"}
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0

            assert 'Ignoring' in c.out
            assert 'markers' in p.lockfile['default']['requests']

            c = p.pipenv('run python -c "import requests;"')
            assert c.return_code == 1

    @pytest.mark.install
    @pytest.mark.vcs
    @pytest.mark.tablib
    def test_install_editable_git_tag(self, pip_src_dir):
        with PipenvInstance() as p:
            c = p.pipenv('install -e git+git://github.com/kennethreitz/tablib.git@v0.12.1#egg=tablib')
            assert c.return_code == 0
            assert 'tablib' in p.pipfile['packages']
            assert 'tablib' in p.lockfile['default']
            assert 'git' in p.lockfile['default']['tablib']
            assert p.lockfile['default']['tablib']['git'] == 'git://github.com/kennethreitz/tablib.git'
            assert 'ref' in p.lockfile['default']['tablib']            

    @pytest.mark.run
    @pytest.mark.alt
    @pytest.mark.install
    def test_alternative_version_specifier(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = {version = "*"}
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0

            assert 'requests' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'certifi' in p.lockfile['default']
            assert 'chardet' in p.lockfile['default']

            c = p.pipenv('run python -c "import requests; import idna; import certifi;"')
            assert c.return_code == 0

    @pytest.mark.bad
    @pytest.mark.install
    def test_bad_packages(self):

        with PipenvInstance() as p:
            c = p.pipenv('install NotAPackage')
            assert c.return_code > 0

    @pytest.mark.dotvenv
    def test_venv_in_project(self):

        with temp_environ():
            os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
            with PipenvInstance() as p:
                c = p.pipenv('install requests')
                assert c.return_code == 0

                assert normalize_drive(p.path) in p.pipenv('--venv').out

    @pytest.mark.dotvenv
    @pytest.mark.install
    @pytest.mark.complex
    @pytest.mark.shell
    @pytest.mark.windows
    @pytest.mark.pew
    def test_shell_nested_venv_in_project(self):
        import subprocess
        with temp_environ():
            os.environ['PIPENV_VENV_IN_PROJECT'] = '1'
            os.environ['PIPENV_IGNORE_VIRTUALENVS'] = '1'
            os.environ['PIPENV_SHELL_COMPAT'] = '1'
            with PipenvInstance(chdir=True) as p:
                # Signal to pew to look in the project directory for the environment
                os.environ['WORKON_HOME'] = p.path
                project = Project()
                c = p.pipenv('install requests')
                assert c.return_code == 0
                assert 'requests' in p.pipfile['packages']
                assert 'requests' in p.lockfile['default']
                # Check that .venv now shows in pew's managed list
                pew_list = delegator.run('pew ls')
                assert '.venv' in pew_list.out
                # Check for the venv directory
                c = delegator.run('pew dir .venv')
                # Compare pew's virtualenv path to what we expect
                venv_path = get_windows_path(project.project_directory, '.venv')
                # os.path.normpath will normalize slashes
                assert venv_path == normalize_drive(os.path.normpath(c.out.strip()))
                # Have pew run 'pip freeze' in the virtualenv
                # This is functionally the same as spawning a subshell
                # If we can do this we can theoretically amke a subshell
                # This test doesn't work on *nix
                if os.name == 'nt':
                    args = ['pew', 'in', '.venv', 'pip', 'freeze']
                    process = subprocess.Popen(
                        args,
                        shell=True,
                        universal_newlines=True,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    out, _ = process.communicate()
                    assert any(req.startswith('requests') for req in out.splitlines()) is True


    @pytest.mark.run
    @pytest.mark.dotenv
    def test_env(self):

        with PipenvInstance(pipfile=False) as p:
            with open('.env', 'w') as f:
                f.write('HELLO=WORLD')

            c = p.pipenv('run python -c "import os; print(os.environ[\'HELLO\'])"')
            assert c.return_code == 0
            assert 'WORLD' in c.out

    @pytest.mark.e
    @pytest.mark.install
    @pytest.mark.skip(reason="this doesn't work on windows")
    def test_e_dot(self, pip_src_dir):

        with PipenvInstance() as p:
            path = os.path.abspath(os.path.sep.join([os.path.dirname(__file__), '..']))
            c = p.pipenv('install -e \'{0}\' --dev'.format(path))

            assert c.return_code == 0

            key = [k for k in p.pipfile['dev-packages'].keys()][0]
            assert 'path' in p.pipfile['dev-packages'][key]
            assert 'requests' in p.lockfile['develop']

    @pytest.mark.code
    @pytest.mark.install
    def test_code_import_manual(self):

        with PipenvInstance() as p:

            with PipenvInstance(chdir=True) as p:
                with open('t.py', 'w') as f:
                    f.write('import requests')

                p.pipenv('install -c .')
                assert 'requests' in p.pipfile['packages']

    @pytest.mark.code
    @pytest.mark.check
    @pytest.mark.unused
    def test_check_unused(self):

        with PipenvInstance() as p:

            with PipenvInstance(chdir=True) as p:
                with open('t.py', 'w') as f:
                    f.write('import git')

                p.pipenv('install GitPython')
                p.pipenv('install requests')
                p.pipenv('install tablib')

                assert 'requests' in p.pipfile['packages']

                c = p.pipenv('check --unused .')
                assert 'GitPython' not in c.out
                assert 'tablib' in c.out

    @pytest.mark.check
    @pytest.mark.style
    def test_flake8(self):

        with PipenvInstance() as p:

            with PipenvInstance(chdir=True) as p:
                with open('t.py', 'w') as f:
                    f.write('import requests')

                c = p.pipenv('check --style .')
                assert 'requests' in c.out

    @pytest.mark.extras
    @pytest.mark.install
    @pytest.mark.requirements
    def test_requirements_to_pipfile(self):

        with PipenvInstance(pipfile=False, chdir=True) as p:

            # Write a requirements file
            with open('requirements.txt', 'w') as f:
                f.write('requests[socks]==2.18.1\n')

            c = p.pipenv('install')
            assert c.return_code == 0
            print(c.out)
            print(c.err)
            print(delegator.run('ls -l').out)

            # assert stuff in pipfile
            assert 'requests' in p.pipfile['packages']
            assert 'extras' in p.pipfile['packages']['requests']

            # assert stuff in lockfile
            assert 'requests' in p.lockfile['default']
            assert 'chardet' in p.lockfile['default']
            assert 'idna' in p.lockfile['default']
            assert 'urllib3' in p.lockfile['default']
            assert 'pysocks' in p.lockfile['default']

    @pytest.mark.code
    @pytest.mark.virtualenv
    def test_activate_virtualenv_no_source(self):
        command = activate_virtualenv(source=False)
        venv = Project().virtualenv_location

        assert command == '{0}/bin/activate'.format(venv)

    @pytest.mark.lock
    @pytest.mark.requirements
    def test_lock_requirements_file(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "==2.14.0"
flask = "==0.12.2"
[dev-packages]
pytest = "==3.1.1"
                """.strip()
                f.write(contents)

            req_list = ("requests==2.14.0", "flask==0.12.2")

            dev_req_list = ("pytest==3.1.1",)

            c = p.pipenv('lock -r')
            d = p.pipenv('lock -r -d')
            assert c.return_code == 0
            assert d.return_code == 0

            for req in req_list:
                assert req in c.out

            for req in dev_req_list:
                assert req not in c.out
                assert req in d.out

    @pytest.mark.lock
    @pytest.mark.complex
    def test_complex_lock_with_vcs_deps(self, pip_src_dir):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
click = "==6.7"

[dev-packages]
requests = {git = "https://github.com/requests/requests", egg = "requests"}
                """.strip()
                f.write(contents)

            c = p.pipenv('install')
            assert c.return_code == 0
            lock = p.lockfile
            assert 'requests' in lock['develop']
            assert 'click' in lock['default']

            c = p.pipenv('run pip install -e git+https://github.com/dateutil/dateutil#egg=python_dateutil')
            assert c.return_code == 0

            c = p.pipenv('lock')
            assert c.return_code == 0
            lock = p.lockfile
            assert 'requests' in lock['develop']
            assert 'click' in lock['default']
            assert 'python_dateutil' not in lock['default']
            assert 'python_dateutil' not in lock['develop']

    @pytest.mark.lock
    @pytest.mark.requirements
    @pytest.mark.complex
    @pytest.mark.maya
    def test_complex_deps_lock_and_install_properly(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
maya = "*"
                """.strip()
                f.write(contents)

            c = p.pipenv('lock')
            assert c.return_code == 0

            c = p.pipenv('install')
            assert c.return_code == 0

    @pytest.mark.lock
    @pytest.mark.install
    @pytest.mark.system
    @pytest.mark.skipif(os.name != 'posix', reason="Windows doesn't have a root")
    def test_resolve_system_python_no_virtualenv(self):
        """Ensure we don't error out when we are in a folder off of / and doing an install using --system,
        which used to cause the resolver and PIP_PYTHON_PATH to point at /bin/python
        
        Sample dockerfile:
        FROM python:3.6-alpine3.6

        RUN set -ex && pip install pipenv --upgrade
        RUN set -ex && mkdir /app
        COPY Pipfile /app/Pipfile

        WORKDIR /app
        """
        with temp_environ():
            os.environ['PIPENV_IGNORE_VIRTUALENVS'] = '1'
            os.environ['PIPENV_USE_SYSTEM'] = '1'
            with PipenvInstance(chdir=True) as p:
                os.chdir('/tmp')
                c = p.pipenv('install --system xlrd')
                assert c.return_code == 0
                for fn in ['Pipfile', 'Pipfile.lock']:
                    path = os.path.join('/tmp', fn)
                    if os.path.exists(path):
                        os.unlink(path)

    @pytest.mark.requirements
    @pytest.mark.complex
    def test_complex_lock_changing_candidate(self):
        # The requests candidate will change from latest to <2.12.

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
"docker-compose" = "==1.16.0"
docker = "<2.7"
requests = "*"
                """.strip()
                f.write(contents)

            c = p.pipenv('lock')
            assert c.return_code == 0
            assert parse_version(p.lockfile['default']['requests']['version'][2:]) < parse_version('2.12')

            c = p.pipenv('install')
            assert c.return_code == 0

    @pytest.mark.extras
    @pytest.mark.lock
    @pytest.mark.requirements
    @pytest.mark.complex
    def test_complex_lock_deep_extras(self):
        # records[pandas] requires tablib[pandas] which requires pandas.

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
records = {extras = ["pandas"], version = "==0.5.2"}
                """.strip()
                f.write(contents)

            c = p.pipenv('lock')
            assert c.return_code == 0
            assert 'tablib' in p.lockfile['default']
            assert 'pandas' in p.lockfile['default']

            c = p.pipenv('install')
            assert c.return_code == 0

    @pytest.mark.lock
    @pytest.mark.deploy
    def test_deploy_works(self):

        with PipenvInstance() as p:
            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "==2.14.0"
flask = "==0.12.2"
[dev-packages]
pytest = "==3.1.1"
                """.strip()
                f.write(contents)

            p.pipenv('lock')

            with open(p.pipfile_path, 'w') as f:
                contents = """
[packages]
requests = "==2.14.0"
                """.strip()
                f.write(contents)

            c = p.pipenv('install --deploy')
            assert c.return_code > 0

    @pytest.mark.install
    @pytest.mark.files
    @pytest.mark.urls
    def test_urls_work(self):

        with PipenvInstance() as p:

            c = p.pipenv('install https://github.com/divio/django-cms/archive/release/3.4.x.zip')
            key = [k for k in p.pipfile['packages'].keys()][0]
            dep = p.pipfile['packages'][key]

            assert 'file' in dep
            assert c.return_code == 0

            key = [k for k in p.lockfile['default'].keys()][0]
            dep = p.lockfile['default'][key]

            assert 'file' in dep

    @pytest.mark.install
    @pytest.mark.files
    @pytest.mark.resolver
    def test_local_package(self, pip_src_dir):
        """This test ensures that local packages (directories with a setup.py)
        installed in editable mode have their dependencies resolved as well"""
        file_name = 'tablib-0.12.1.tar.gz'
        package = 'tablib-0.12.1'
        # Not sure where travis/appveyor run tests from
        test_dir = os.path.dirname(os.path.abspath(__file__))
        source_path = os.path.abspath(os.path.join(test_dir, 'test_artifacts', file_name))
        with PipenvInstance() as p:
            # This tests for a bug when installing a zipfile in the current dir
            copy_to = os.path.join(p.path, file_name)
            shutil.copy(source_path, copy_to)
            import tarfile
            with tarfile.open(copy_to, 'r:gz') as tgz:
                tgz.extractall(path=p.path)
            c = p.pipenv('install -e {0}'.format(package))
            assert c.return_code == 0
            assert all(pkg in p.lockfile['default'] for pkg in ['xlrd', 'xlwt', 'pyyaml', 'odfpy'])


    @pytest.mark.install
    @pytest.mark.files
    def test_local_zipfiles(self):
        file_name = 'tablib-0.12.1.tar.gz'
        # Not sure where travis/appveyor run tests from
        test_dir = os.path.dirname(os.path.abspath(__file__))
        source_path = os.path.abspath(os.path.join(test_dir, 'test_artifacts', file_name))

        with PipenvInstance() as p:
            # This tests for a bug when installing a zipfile in the current dir
            shutil.copy(source_path, os.path.join(p.path, file_name))

            c = p.pipenv('install {}'.format(file_name))
            key = [k for k in p.pipfile['packages'].keys()][0]
            dep = p.pipfile['packages'][key]

            assert 'file' in dep or 'path' in dep
            assert c.return_code == 0

            key = [k for k in p.lockfile['default'].keys()][0]
            dep = p.lockfile['default'][key]

            assert 'file' in dep or 'path' in dep


    @pytest.mark.install
    @pytest.mark.files
    @pytest.mark.urls
    def test_install_remote_requirements(self):
        with PipenvInstance() as p:
            # using a github hosted requirements.txt file
            c = p.pipenv('install -r https://raw.githubusercontent.com/kennethreitz/pipenv/3688148ac7cfecefb085c474b092c31d791952c1/tests/test_artifacts/requirements.txt')

            assert c.return_code == 0
            # check Pipfile with versions
            assert 'requests' in p.pipfile['packages']
            assert p.pipfile['packages']['requests'] == u'==2.18.4'
            assert 'records' in p.pipfile['packages']
            assert p.pipfile['packages']['records'] == u'==0.5.2'

            # check Pipfile.lock
            assert 'requests' in p.lockfile['default']
            assert 'records' in p.lockfile['default']


    @pytest.mark.install
    @pytest.mark.files
    def test_relative_paths(self):
        file_name = 'tablib-0.12.1.tar.gz'
        test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        source_path = os.path.abspath(os.path.join(test_dir, 'test_artifacts', file_name))

        with PipenvInstance() as p:
            artifact_dir = 'artifacts'
            artifact_path = os.path.join(p.path, artifact_dir)
            mkdir_p(artifact_path)
            shutil.copy(source_path, os.path.join(artifact_path, file_name))
            # Test installing a relative path in a subdirectory
            c = p.pipenv('install {}/{}'.format(artifact_dir, file_name))
            key = [k for k in p.pipfile['packages'].keys()][0]
            dep = p.pipfile['packages'][key]

            assert 'path' in dep
            assert Path(os.path.join('.', artifact_dir, file_name)) == Path(dep['path'])
            assert c.return_code == 0

    @pytest.mark.install
    @pytest.mark.local_file
    def test_install_local_file_collision(self):
        with PipenvInstance() as p:
            target_package = 'alembic'
            fake_file = os.path.join(p.path, target_package)
            with open(fake_file, 'w') as f:
                f.write('')
            c = p.pipenv('install {}'.format(target_package))
            assert c.return_code == 0
            assert target_package in p.pipfile['packages']
            assert p.pipfile['packages'][target_package] == '*'
            assert target_package in p.lockfile['default']
