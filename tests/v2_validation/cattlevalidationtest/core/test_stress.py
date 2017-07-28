from common_fixtures import *  # NOQA
from test_upgrade import *  # NOQA
import jinja2
import os

upgrade_loops = int(os.environ.get("UPGRADE_LOOPS", "10"))

if_stress_testing = pytest.mark.skipif(
    os.environ.get("STRESS_TESTING") != "true",
    reason='STRESS_TESTING is not true')


# Execute command in container
def execute_cmd(pod, cmd, namespace):
    result = execute_kubectl_cmds(
                "exec " + pod + " --namespace=" + namespace + " -- " + cmd)
    return result


def render(tpl_path, context):
    path, filename = os.path.split(tpl_path)
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(path)
    ).get_template(filename).render(context)


def check_k8s_dashboard():
    k8s_client = kubectl_client_con["k8s_client"]
    project_id = k8s_client.list_project()[0].id
    dashboard_url = rancher_server_url() + \
        '/r/projects/' + \
        project_id + \
        '/kubernetes-dashboard:9090/'
    try:
        r = requests.get(dashboard_url)
        r.close()
        return r.ok
    except requests.ConnectionError:
        logger.info("Connection Error - " + url)
        return False


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
            "kubernetes",
            "kubernetes-ingress-lbs",
            "kubernetes-loadbalancers"
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


def validate_helm():
    response = execute_helm_cmds("create validation-nginx")
    print response
    get_response = execute_helm_cmds("install validation-nginx \
        --name stresstest --namespace stresstest-ns --replace")

    if "STATUS: DEPLOYED" not in get_response:
        print "dies at install"
        return False
    time.sleep(10)

    get_response = execute_kubectl_cmds(
                    "get svc stresstest-validation-ng --namespace \
                    stresstest-ns -o json")
    print get_response
    service = json.loads(get_response)
    assert service['metadata']['name'] == "stresstest-validation-ng"

    waitfor_pods(
        selector="app=stresstest-validation-ng",
        namespace="stresstest-ns", number=1)
    get_response = execute_kubectl_cmds(
        "get pods -o json -l 'app=stresstest-validation-ng'  ")
    pod = json.loads(get_response)

    for pod in pod["items"]:
        assert pod["status"]["phase"] == "Running"
        assert pod['kind'] == "Pod"

    # Remove the release
    response = execute_helm_cmds("delete --purge stresstest")
    print response
    time.sleep(10)
    response = execute_helm_cmds("ls -q stresstest")
    assert response is ''
    return True


@if_stress_testing
def test_k8s_dashboard(kube_hosts):
    assert check_k8s_dashboard()


@if_stress_testing
def test_deploy_k8s_yaml(kube_hosts):
    input_config = {
        "namespace": "stresstest-ns-1",
        "port_ext": "1"
    }
    create_stack(input_config)
    time.sleep(120)
    validate_stack(input_config)


@if_stress_testing
def test_validate_helm(kube_hosts):
    assert validate_helm()


@if_stress_testing
def test_upgrade_validate_k8s(kube_hosts, rancher_cli_container):
    input_config = {
        "namespace": "stresstest-ns-1",
        "port_ext": "1"
    }
    for i in range(2, upgrade_loops):
        force_upgrade_stack("ipsec")
        waitfor_infra_stacks()
        time.sleep(600)
        assert validate_kubectl()
        assert check_k8s_dashboard()
        modify_stack(input_config)
        time.sleep(120)
        # New stack
        input_config = {
            "namespace": "stresstest-ns-"+str(i),
            "port_ext": str(i)
        }
        create_stack(input_config)
        time.sleep(120)
        validate_stack(input_config)
        assert validate_helm()
