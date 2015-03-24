r"""
Summary
---------

Test usage of docker 'wait' command

Operational Summary
----------------------

#. starts all containers defined in containers
#. prepares the wait command
#. prepares the expected results
#. executes the test command in all containers
#. executes the wait command
#. waits until all containers should be finished
#. analyze results
"""
import random
import re
import time

from dockertest import config
from dockertest import subtest
from dockertest.containers import DockerContainers
from dockertest.dockercmd import AsyncDockerCmd
from dockertest.dockercmd import DockerCmd
from dockertest.images import DockerImage
from dockertest.output import OutputGood
from dockertest.output import OutputNotBad
from dockertest.subtest import SubSubtest
from dockertest.xceptions import DockerTestError
from dockertest.xceptions import DockerTestNAError


class wait(subtest.SubSubtestCaller):

    """ Subtest caller """
    config_section = 'docker_cli/wait'


class wait_base(SubSubtest):

    """ Base class """
    re_sleep = re.compile(r'sleep (\d+)')
    re_exit = re.compile(r'exit (\d+)')

    # TODO: Check other tests/upcoming tests, add to config module?
    def get_object_config(self, obj_name, key, default=None):
        return self.config.get(key + '_' + obj_name,
                               self.config.get(key, default))

    def init_substuff(self):
        # sub_stuff['containers'] is list of dicts containing:
        # 'result' - DockerCmd process (detached)
        # 'id' - id or name of the container
        # 'exit_status' - expected exit code after test command
        # 'test_cmd' - AsyncDockerCmd of the test command (attach ps)
        # 'test_cmd_stdin' - stdin used by 'test_cmd'
        # 'sleep_time' - how long it takes after test_cmd before exit
        self.sub_stuff['containers'] = []
        self.sub_stuff['wait_cmd'] = None
        self.sub_stuff['wait_stdout'] = None    # Expected wait stdout output
        self.sub_stuff['wait_stderr'] = None    # Expected wait stderr output
        self.sub_stuff['wait_result'] = None
        self.sub_stuff['wait_duration'] = None  # Wait for tested conts
        self.sub_stuff['wait_should_fail'] = None   # Expected wait failure
        # Sleep after wait finishes (for non-tested containers to finish
        self.sub_stuff['sleep_after'] = None

    def init_container(self, name):
        subargs = self.get_object_config(name, 'run_options_csv')
        if subargs:
            subargs = [arg for arg in
                       self.config['run_options_csv'].split(',')]
        else:
            subargs = []
        image = DockerImage.full_name_from_defaults(self.config)
        subargs.append(image)
        subargs.append("bash")
        cont = {'result': DockerCmd(self, 'run', subargs, 10)}
        self.sub_stuff['containers'].append(cont)
        cont_id = cont['result'].execute().stdout.strip()
        cont['id'] = cont_id

        # Cmd must contain one "exit $exit_status"
        cmd = self.get_object_config(name, 'exec_cmd')
        cont['exit_status'] = self.re_exit.findall(cmd)[0]
        sleep = self.re_sleep.findall(cmd)
        if sleep:
            sleep = int(sleep[0])
            cont['sleep_time'] = sleep
        else:
            cont['sleep_time'] = 0
        cont['test_cmd'] = AsyncDockerCmd(self, "attach", [cont_id])
        cont['test_cmd_stdin'] = cmd

    def init_use_names(self, use_names='IDS'):
        if use_names == 'IDS':  # IDs are already set
            return
        else:
            if use_names == 'RANDOM':    # log the current seed
                try:
                    seed = self.config["random_seed"]
                except ValueError:
                    seed = random.random()
                self.logdebug("Using random seed: %s", seed)
                rand = random.Random(seed)
            conts = self.sub_stuff['containers']
            containers = DockerContainers(self)
            containers = containers.list_containers()
            cont_ids = [cont['id'] for cont in conts]
            for cont in containers:
                if cont.long_id in cont_ids:
                    if use_names == 'RANDOM' and rand.choice((True, False)):
                        continue    # 50% chance of using id vs. name
                    # replace the id with name
                    cont_idx = cont_ids.index(cont.long_id)
                    conts[cont_idx]['id'] = cont.container_name

    def init_wait_for(self, wait_for, subargs):
        if not wait_for:
            raise DockerTestNAError("No container specified in config. to "
                                    "wait_for.")
        conts = self.sub_stuff['containers']
        end = self.config['invert_missing']
        wait_duration = 0
        wait_stdout = []
        wait_stderr = []

        for cont in wait_for.split(' '):  # digit or _$STRING
            if cont.isdigit():
                cont = conts[int(cont)]
                subargs.append(cont['id'])
                wait_stdout.append(cont['exit_status'])
                wait_duration = max(wait_duration, cont['sleep_time'])
            else:
                subargs.append(cont[1:])
                regex = self.config['missing_stderr'] % cont[1:]
                wait_stderr.append(regex)
                end = True
        self.sub_stuff['wait_stdout'] = wait_stdout
        self.sub_stuff['wait_stderr'] = wait_stderr
        self.sub_stuff['wait_should_fail'] = end
        self.sub_stuff['wait_duration'] = wait_duration
        self.sub_stuff['wait_cmd'] = DockerCmd(self, 'wait', subargs,
                                               wait_duration + 20)
        max_duration = max(conts, key=lambda x: x['sleep_time'])['sleep_time']
        self.sub_stuff['sleep_after'] = max(0, max_duration - wait_duration)

    def prep_wait_cmd(self, wait_options_csv=None):
        if wait_options_csv is not None:
            subargs = [arg for arg in
                       self.config['wait_options_csv'].split(',')]
        else:
            subargs = []
        self.init_wait_for(self.config['wait_for'], subargs)

    def initialize(self):
        super(wait_base, self).initialize()
        config.none_if_empty(self.config)
        self.init_substuff()

        # Container
        for name in self.config['containers'].split():
            self.init_container(name)

        self.init_use_names(self.config.get('use_names', False))

        # Prepare the "wait" command
        self.prep_wait_cmd(self.config.get('wait_options_csv'))

    def run_once(self):
        super(wait_base, self).run_once()
        for cont in self.sub_stuff['containers']:
            self.logdebug("Executing %s, stdin %s", cont['test_cmd'],
                          cont['test_cmd_stdin'])
            cont['test_cmd'].execute(cont['test_cmd_stdin'] + "\n")
        self.sub_stuff['wait_cmd'].execute()
        self.sub_stuff['wait_results'] = self.sub_stuff['wait_cmd'].cmdresult
        self.logdebug("Wait finished, sleeping for %ss for non-tested "
                      "containers to finish.", self.sub_stuff['sleep_after'])
        time.sleep(self.sub_stuff['sleep_after'])

    def postprocess(self):
        # Check if execution took the right time (SIGTERM 0s vs. SIGKILL 10s)
        super(wait_base, self).postprocess()
        wait_results = self.sub_stuff['wait_results']

        for stdio_name in ('stdout', 'stderr'):
            result = getattr(wait_results, stdio_name)
            one_matched = False
            paterns = self.sub_stuff['wait_%s' % stdio_name]
            if not paterns:
                continue
            for pattern in paterns:
                regex = re.compile(pattern, re.MULTILINE)
                if bool(regex.search(result)):
                    one_matched = True
                    break
            if self.sub_stuff['wait_should_fail']:
                condition = one_matched
            else:
                condition = not one_matched
            self.failif(condition,
                        "Expected %s match one of '%s' in %s:\n%s"
                        % (condition,
                           self.sub_stuff['wait_%s' % stdio_name],
                           stdio_name, result))
        OutputNotBad(wait_results)
        if self.sub_stuff['wait_should_fail']:
            self.failif(wait_results.exit_status == 0,
                        "Wait command should have failed but "
                        "passed instead: %s" % wait_results)
        else:
            OutputGood(wait_results)
            self.failif(wait_results.exit_status != 0,
                        "Wait exit_status should be "
                        "zero, but is %s instead" % wait_results.exit_status)
        exp = self.sub_stuff['wait_duration']
        self.failif(wait_results.duration > exp + 3,
                    "Execution of wait took longer,"
                    " than expected. (%s %s+-3s)"
                    % (wait_results.duration, exp))
        self.failif(wait_results.duration < exp - 3,
                    "Execution of wait took less, "
                    "than expected. (%s %s+-3s)"
                    % (wait_results.duration, exp))
        for cmd in (cont['test_cmd']
                    for cont in self.sub_stuff['containers']):
            self.failif(not cmd.done, "Wait passed even thought one of the "
                        "test commands execution did not finish...\n%s")
            OutputGood(cmd.wait(0))

    def cleanup(self):
        # Removes the docker safely
        failures = []
        super(wait_base, self).cleanup()
        if not self.sub_stuff.get('containers'):
            return  # Docker was not created, we are clean
        containers = DockerContainers(self).list_containers()
        test_conts = self.sub_stuff.get('containers')
        for cont in test_conts:
            if 'id' not in cont:  # Execution failed, we don't have id
                failures.append("Container execution failed, can't verify what"
                                "/if remained in system: %s"
                                % cont['result'])
            if 'test_cmd' in cont:
                if not cont['test_cmd'].done:
                    # Actual killing happens below
                    failures.append("Test cmd %s had to be killed."
                                    % (cont['test_cmd']))
        cont_ids = [cont['id'] for cont in test_conts]
        for cont in containers:
            if cont.long_id in cont_ids or cont.container_name in cont_ids:
                cmdresult = DockerCmd(self, 'rm',
                                      ['--force', '--volumes',
                                       cont.long_id]).execute()
                if cmdresult.exit_status != 0:
                    failures.append("Fail to remove container %s: %s"
                                    % (cont.long_id, cmdresult))
        if failures:
            raise DockerTestError("Cleanup failed:\n%s" % failures)


class no_wait(wait_base):

    """
    Test usage of docker 'wait' command (waits only for containers, which
    should already exited. Expected execution duration is 0s)

    initialize:
    1) starts all containers defined in containers
    2) prepares the wait command
    3) prepares the expected results
    run_once:
    4) executes the test command in all containers
    5) executes the wait command
    6) waits until all containers should be finished
    postprocess:
    7) analyze results
    """
    pass


class wait_first(wait_base):

    """
    Test usage of docker 'wait' command (first container exits after 10s,
    others immediately. Expected execution duration is 10s)

    initialize:
    1) starts all containers defined in containers
    2) prepares the wait command
    3) prepares the expected results
    run_once:
    4) executes the test command in all containers
    5) executes the wait command
    6) waits until all containers should be finished
    postprocess:
    7) analyze results
    """
    pass


class wait_last(wait_base):

    """
    Test usage of docker 'wait' command (last container exits after 10s,
    others immediately. Expected execution duration is 10s)

    initialize:
    1) starts all containers defined in containers
    2) prepares the wait command
    3) prepares the expected results
    run_once:
    4) executes the test command in all containers
    5) executes the wait command
    6) waits until all containers should be finished
    postprocess:
    7) analyze results
    """
    pass


class wait_missing(wait_base):

    """
    Test usage of docker 'wait' command (first and last containers doesn't
    exist, second takes 10s to finish and the rest should finish immediately.
    Expected execution duration is 10s with 2 exceptions)

    initialize:
    1) starts all containers defined in containers
    2) prepares the wait command
    3) prepares the expected results
    run_once:
    4) executes the test command in all containers
    5) executes the wait command
    6) waits until all containers should be finished
    postprocess:
    7) analyze results
    """
    pass
