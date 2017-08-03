from common_fixtures import *  # NOQA
from test_upgrade import *  # NOQA
import os

upgrade_loops = int(os.environ.get("UPGRADE_LOOPS", "10"))

if_stress_testing = pytest.mark.skipif(
    os.environ.get("STRESS_TESTING") != "true",
    reason='STRESS_TESTING is not true')


def force_upgrade_stack(stack_name):
    k8s_client = kubectl_client_con["k8s_client"]
    access_key = k8s_client._access_key
    secret_key = k8s_client._secret_key

    force_up_commands = [
        "export RANCHER_URL=" + rancher_server_url(),
        "export RANCHER_ACCESS_KEY=" + access_key,
        "export RANCHER_SECRET_KEY=" + secret_key,
        "export RANCHER_ENVIRONMENT=" + PROJECT_ID,
        "cd rancher-v*",
        "./rancher export " + stack_name,
        "./rancher up --force-upgrade --confirm-upgrade " +
        "-d -s " + stack_name + " --batch-size 1 " +
        "--interval 1000 -f " + stack_name + "/docker-compose.yml" +
        " --rancher-file=" + stack_name + "/rancher-compose.yml"
    ]

    logger.info("Final command: " + " ; ".join(force_up_commands))

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(
            rancher_cli_con["host"].ipAddresses()[0].address, username="root",
            password="root", port=int(rancher_cli_con["port"]))
    except Exception as e:
        logger.info("SSH Connection Error")
        raise e
    stdin, stdout, stderr = ssh.exec_command(
                                            " ; ".join(force_up_commands),
                                            timeout=1200)
    response = stdout.readlines()
    error = stderr.readlines()
    logger.info(response)
    logger.info(error)

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
        logger.info("Starting Loop: " + str(i))
        # force_upgrade_stack("ipsec")
        force_upgrade_stack("kubernetes")
        waitfor_infra_stacks()
        time.sleep(300)
        assert validate_kubectl()
        logger.info("End of Loop: " + str(i))
