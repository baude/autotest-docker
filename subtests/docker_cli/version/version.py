r"""
Summary
---------

Test output of docker version command

Operational Summary
----------------------

#. Run docker version command
#. Check output
#. compare to daemon API version

Prerequisites
---------------

None
"""

import os.path
from autotest.client import utils
from dockertest import subtest
from dockertest.output import OutputGood
from dockertest.output import DockerVersion
from dockertest.output import mustpass
from dockertest.dockercmd import DockerCmd
from dockertest.docker_daemon import SocketClient, which_docker


class version(subtest.Subtest):

    def initialize(self):
        super(version, self).initialize()

    def run_once(self):
        super(version, self).run_once()
        # 1. Run with no options
        nfdc = DockerCmd(self, "version")
        self.stuff['cmdresult'] = mustpass(nfdc.execute())

    def postprocess(self):
        super(version, self).postprocess()
        # Raise exception on Go Panic or usage help message
        outputgood = OutputGood(self.stuff['cmdresult'])
        docker_version = DockerVersion(outputgood.stdout_strip)
        info = ("docker version client: %s server %s"
                % (docker_version.client, docker_version.server))
        self.loginfo("Found %s", info)
        with open(os.path.join(self.job.sysinfo.sysinfodir,
                               'docker_version'), 'wb') as info_file:
            info_file.write("%s\n" % info)
        with open(os.path.join(self.job.sysinfo.sysinfodir,
                               'docker_rpm'), 'wb') as rpm_file:
            rpm_file.write(self._docker_rpm())
        self.verify_version(docker_version)

    @staticmethod
    def _docker_rpm():
        return utils.run("rpm -q %s" % which_docker()).stdout

    def verify_version(self, docker_version):
        # TODO: Make URL to daemon configurable
        client = SocketClient()
        _version = client.version()
        client_version = _version['Version']
        self.failif(client_version != docker_version.client,
                    "Docker cli version %s does not match docker client API "
                    "version %s" % (client_version, docker_version.client))
        self.loginfo("Docker cli version matches docker client API version")
