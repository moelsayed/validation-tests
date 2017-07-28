from common_fixtures import *  # NOQA
from test_upgrade import *  # NOQA
import jinja2
import os

upgrade_loops = int(os.environ.get("UPGRADE_LOOPS", "10"))

if_stress_testing = pytest.mark.skipif(
    os.environ.get("STRESS_TESTING") != "true",
    reason='STRESS_TESTING is not true')


def force_upgrade_stack(stack_name):
    k8s_client = kubectl_client_con["k8s_client"]
    stack = k8s_client.list_stack(name=stack_name)[0]
    stack_config = stack.exportconfig()
    docker_compose = stack_config.dockerComposeConfig
    rancher_compose = stack_config.rancherComposeConfig
    cli_command = "up --force-upgrade --confirm-upgrade " + \
                  "-d -s " + stack_name + " --batch-size 1 --interval 1000"
    execute_rancher_cli(k8s_client, stack_name, cli_command,
                        docker_compose=docker_compose,
                        rancher_compose=rancher_compose)
    env = k8s_client.list_stack(name=stack_name)
    assert len(env) == 1
    environment = env[0]
    wait_for_condition(
        k8s_client, environment,
        lambda x: x.healthState == "healthy",
        lambda x: 'State is: ' + x.healthState,
        timeout=1200)


def waitfor_infra_stacks():
    k8s_client = kubectl_client_con["k8s_client"]
    infra_stacks = [
            "ipsec",
            "network-services",
            "healthcheck",
            "kubernetes"
            ]
    for stack_name in infra_stacks:
        env = k8s_client.list_stack(name=stack_name)
        assert len(env) == 1
        environment = env[0]
        wait_for_condition(
            k8s_client, environment,
            lambda x: x.healthState == "healthy",
            lambda x: 'State is: ' + x.healthState,
            timeout=1200)


def validate_kubectl():
    # make sure that kubectl is working
    started = time.time()
    while time.time() - started < 1200:
        while True:
            try:
                get_response = execute_kubectl_cmds("get nodes -o json")
                break
            except:
                time.sleep(2)
                continue
        nodes = json.loads(get_response)
        if len(nodes['items']) == kube_host_count:
            ready_flag = True
            for node in nodes['items']:
                logger.info("node name: " + str(node['metadata']['name']))
                if node['status']['conditions'][3]['status'] != "True":
                    ready_flag = False
            if ready_flag:
                logger.info("hosts found after: " + str(time.time() - started))
                return True
        time.sleep(2)
    return False


@if_stress_testing
def test_upgrade_validate_k8s(kube_hosts, rancher_cli_container):
    for i in range(1, upgrade_loops):
        force_upgrade_stack("ipsec")
        waitfor_infra_stacks()
        time.sleep(300)
        assert validate_kubectl()
