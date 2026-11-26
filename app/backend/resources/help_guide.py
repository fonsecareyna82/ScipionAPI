"""The sections of the documentation (scipion-docs) for its users, for the help chat.

Written by scripts/build_help_guide.py: do not change it by hand."""

GUIDE = [{'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'What this page covers',
  'text': 'This page describes environment variables managed from the ScipionWeb interface.\n'
          '\n'
          'It is different from the server-side .env file used to configure ScipionAPI itself. For the low-level '
          'runtime file, see Environment Variables (.env).\n'
          '\n'
          'The Settings environment section is intended for variables that ScipionWeb and plugin execution need to '
          'read at runtime, especially path variables used by external scientific software.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#what-this-page-covers'},
 {'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'Why this is useful',
  'text': 'Some Scipion plugins can use external software that has already been installed outside the plugin '
          'installation process.\n'
          '\n'
          'In those cases, you may not want the plugin installer to download or install binaries again. Instead, you '
          'can:\n'
          '\n'
          '1. install only the Python package for the plugin\n'
          '2. define or update the environment variable expected by that plugin\n'
          '3. point the variable to the existing external software installation\n'
          '4. let ScipionWeb pick up the value without requiring a full service restart\n'
          '\n'
          'This is useful for deployments where large external packages are already managed by administrators, '
          'modules, shared storage, containers, or site-specific installation policies.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#why-this-is-useful'},
 {'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'Hot runtime assimilation',
  'text': 'ScipionWeb is able to assimilate these variables while the system is running. After a variable is created '
          'or modified from Settings, the updated value becomes available to the relevant ScipionWeb runtime context '
          'without forcing users to manually edit server files.\n'
          '\n'
          'Validate after changing variables:\n'
          'Even when ScipionWeb picks up the value dynamically, you should still validate the affected plugin or '
          'protocol after changing an environment variable.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#hot-runtime-assimilation'},
 {'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'Common plugin variable pattern',
  'text': 'Many plugins expect a path variable with a name that follows this pattern:\n'
          '\n'
          'text\n'
          'PLUGINHOME\n'
          '\n'
          'For a real plugin, the prefix normally matches the plugin or external program name. The variable value '
          'should point to the directory where the external software is installed.\n'
          '\n'
          'Examples:\n'
          '\n'
          'text\n'
          'SOMEPLUGINHOME=/opt/software/someplugin\n'
          'EXTERNALTOOLHOME=/shared/apps/externaltool\n'
          'MYPROGRAMHOME=/home/scipion/software/myprogram\n'
          '\n'
          'The exact variable name depends on the plugin. In many cases, the plugin installation or plugin '
          'documentation already defines the expected variable name.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#common-plugin-variable-pattern'},
 {'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'Recommended workflow for external software',
  'text': 'Use this flow when the external software already exists on the server:\n'
          '\n'
          '1. Confirm that the external software is installed and accessible from the ScipionWeb host.\n'
          '2. Install only the Python package for the Scipion plugin, avoiding binary installation if that is the '
          'intended deployment strategy.\n'
          '3. Open Settings in ScipionWeb.\n'
          '4. Go to the environment variables section.\n'
          '5. Add or update the plugin path variable, usually following the PLUGINHOME pattern.\n'
          '6. Save the variable.\n'
          '7. Run a small validation workflow or open a protocol that depends on the plugin.\n'
          '8. Check logs if the plugin still cannot locate the external binary.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#recommended-workflow-for-external-software'},
 {'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'Add a new environment variable',
  'text': '1. Open Settings.\n'
          '2. Locate the environment variables section.\n'
          '3. Select the action to add a new variable.\n'
          '4. Enter the variable name exactly as expected by the plugin.\n'
          '5. Enter the full filesystem path to the external software installation.\n'
          '6. Save the variable.\n'
          '7. Verify that the variable appears in the list.\n'
          '\n'
          'Before saving, check:\n'
          '\n'
          '- the variable name uses the correct uppercase spelling\n'
          '- the path exists on the server where ScipionWeb runs\n'
          '- the user running ScipionWeb has permission to read and execute files from that path\n'
          '- the path points to the software installation root expected by the plugin',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#add-a-new-environment-variable'},
 {'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'Modify an existing variable',
  'text': 'Use modification when the external software was moved, upgraded, or replaced.\n'
          '\n'
          '1. Open Settings.\n'
          '2. Find the existing environment variable.\n'
          '3. Change the value to the new path.\n'
          '4. Save the change.\n'
          '5. Validate the affected plugin or protocol.\n'
          '\n'
          'Changing paths can affect running work:\n'
          'Avoid changing a variable used by active workflows unless you understand the impact. A running or queued '
          'protocol may depend on the previous value.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#modify-an-existing-variable'},
 {'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'Good practice',
  'text': '- keep variable names uppercase and consistent with plugin expectations\n'
          '- use absolute paths, not relative paths\n'
          '- avoid pointing variables to user-specific temporary folders\n'
          '- document externally managed software versions outside ScipionWeb when needed\n'
          '- test a minimal protocol after changing a plugin path\n'
          '- avoid duplicating binary installations when a stable external installation already exists',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#good-practice'},
 {'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'Common mistakes',
  'text': 'Users often run into problems when they:\n'
          '\n'
          '- use the wrong variable name\n'
          '- point the variable to the binary file instead of the expected installation directory\n'
          '- point to a path that exists only on their local workstation, not on the server\n'
          '- forget that the ScipionWeb service user needs filesystem permissions\n'
          '- install plugin binaries unnecessarily even though the external software is already available\n'
          '- update a variable while another workflow is still using the previous path',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#common-mistakes'},
 {'area': 'user-guide',
  'page': 'Environment Variables in Settings',
  'title': 'If a plugin still cannot find the software',
  'text': 'Check:\n'
          '\n'
          '- the exact variable name expected by the plugin\n'
          '- the saved value in ScipionWeb Settings\n'
          '- whether the path exists on the ScipionWeb server\n'
          '- whether the service user has read and execute permissions\n'
          '- whether the plugin expects the root folder, a bin folder, or another specific subdirectory\n'
          '- whether the protocol logs show the environment value being used\n'
          '\n'
          'Useful recovery steps:\n'
          '\n'
          '1. verify the external software path manually on the server\n'
          '2. correct the variable in Settings\n'
          '3. run a small plugin-specific validation protocol\n'
          '4. inspect protocol and backend logs if the path is still not detected',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#if-a-plugin-still-cannot-find-the-software'},
 {'area': 'user-guide',
  'page': 'First Login and Session Basics',
  'title': 'Before you troubleshoot login',
  'text': 'Confirm these basics first:\n'
          '\n'
          '- you are opening the intended environment\n'
          '- the backend instance is actually reachable\n'
          '- your browser is not reusing stale session state from another instance\n'
          '- you are not mixing tabs from different environments',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/first-login/#before-you-troubleshoot-login'},
 {'area': 'user-guide',
  'page': 'First Login and Session Basics',
  'title': 'After login, verify that',
  'text': '- the dashboard loads correctly\n'
          '- the main navigation loads correctly\n'
          '- your user identity appears as expected\n'
          '- the projects area opens without errors\n'
          '- requests complete without browser auth or CORS failures\n'
          '- protected data loads consistently after refresh\n'
          '\n'
          'If the interface appears but project-related data never loads, the problem is often session state or '
          'backend/API connectivity rather than visual rendering.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/first-login/#after-login-verify-that'},
 {'area': 'user-guide',
  'page': 'First Login and Session Basics',
  'title': 'Common first-login problems',
  'text': 'Invalid credentials\n'
          '\n'
          'Check that you are using the correct username, password, and environment.\n'
          '\n'
          'Login works but protected pages fail\n'
          '\n'
          'Possible causes include:\n'
          '\n'
          '- stale token stored in the browser\n'
          '- backend SECRETKEY changed\n'
          '- API base URL mismatch\n'
          '- session state was created against another environment\n'
          '\n'
          'The page loads but actions fail\n'
          '\n'
          'Open browser DevTools and inspect failed network requests under /api.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/first-login/#common-first-login-problems'},
 {'area': 'user-guide',
  'page': 'First Login and Session Basics',
  'title': 'Useful recovery actions',
  'text': 'Try these steps in order:\n'
          '\n'
          '1. log out and log in again\n'
          '2. refresh the page after a clean sign-in\n'
          '3. clear stale browser storage if the instance configuration changed recently\n'
          '4. retry from a private browser window to isolate local-state issues\n'
          '\n'
          'Private window test:\n'
          'A private window is often the fastest way to check whether the issue is caused by cached tokens or stale '
          'local browser state.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/first-login/#useful-recovery-actions'},
 {'area': 'user-guide',
  'page': 'First Login and Session Basics',
  'title': 'Good habits for multi-environment work',
  'text': 'If you regularly switch between local, staging, and production:\n'
          '\n'
          '- keep those environments in clearly named bookmarks\n'
          '- avoid leaving old tabs open for long periods\n'
          '- confirm the URL before changing protected data\n'
          '- do not assume a saved session belongs to the environment you intend to use now',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/first-login/#good-habits-for-multi-environment-work'},
 {'area': 'user-guide',
  'page': 'First Login and Session Basics',
  'title': 'When to ask an administrator for help',
  'text': 'Ask for help when:\n'
          '\n'
          '- the same issue reproduces across browsers or machines\n'
          '- your account should exist but access is denied\n'
          '- the instance is reachable but protected data never loads\n'
          '- the backend appears healthy but login still fails consistently',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/first-login/#when-to-ask-an-administrator-for-help'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'What this settings area is for',
  'text': 'Scipion protocols can be executed directly, but production and shared environments often need a queue '
          'system. A queue system controls when jobs start, how many resources they request, how jobs are cancelled, '
          'and how running jobs are monitored.\n'
          '\n'
          'The Host settings area lets ScipionWeb define:\n'
          '\n'
          '- the host entry used for protocol execution\n'
          '- how a job script is generated\n'
          '- how the job is submitted to the scheduler\n'
          '- how ScipionWeb checks whether the job is still running\n'
          '- how a queued or running job is cancelled\n'
          '- which queues and resource fields are exposed to users\n'
          '\n'
          'For SLURM, this normally means that ScipionWeb writes a job script and submits it with sbatch.\n'
          '\n'
          'Configured from the web interface:\n'
          'In ScipionWeb, host and queue settings are managed from Settings > Host. You do not need to manually edit '
          'hosts.conf for the ScipionWeb workflow described on this page. The examples below show the values that '
          'should be entered in the web form.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#what-this-settings-area-is-for'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'How ScipionWeb manages queued execution',
  'text': 'When a protocol is launched through a configured host, the flow is usually:\n'
          '\n'
          '1. the user launches a protocol from the project workflow or protocol form\n'
          '2. Scipion prepares the protocol command that must be executed\n'
          '3. ScipionWeb builds a queue script from the host submit template configured in Settings\n'
          '4. template placeholders are replaced with protocol and queue values\n'
          '5. the submit command sends the script to the scheduler\n'
          '6. the scheduler returns a job id\n'
          '7. ScipionWeb stores or tracks that job id\n'
          '8. status checks use the configured check command\n'
          '9. cancellation uses the configured cancel command\n'
          '10. protocol logs and outputs are reviewed after execution finishes\n'
          '\n'
          'This means the Host configuration is the bridge between Scipion protocol execution and the external '
          'scheduler.\n'
          '\n'
          'Host settings affect protocol execution:\n'
          'Changes in this section can affect new protocol runs immediately. Avoid editing queue commands, '
          'templates, or resource definitions while users are launching or validating workflows unless the change is '
          'intentional.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#how-scipionweb-manages-queued-execution'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Set it up automatically',
  'text': 'ScipionWeb can fill in this page from the scheduler installed on the server. It works with SLURM, '
          'PBS/Torque and SGE.\n'
          '\n'
          '1. Open Settings → Host and press Detect (top right of the Cluster card).\n'
          "2. ScipionWeb looks for the scheduler's commands (sbatch, qsub…) and reads its queues and their limits "
          '(cores, memory, GPUs, time).\n'
          "3. Choose the queues to offer to users and press Use this. The form is filled in with the scheduler's "
          "commands, a job script and one queue per partition. Each queue's memory, time and GPUs stay within that "
          "queue's limits.\n"
          '4. Review the result, then press Save. Nothing is saved before that.\n'
          '\n'
          'Then press Send a test job, choose a queue, and send it. It submits a tiny job with the form as it is '
          '(saved or not). You see it wait in the queue, run, and print the machine it ran on. If it fails, the '
          'error is shown. Closing the dialog cancels a job that is still waiting.\n'
          '\n'
          'What cannot be detected:\n'
          'Settings that only your cluster knows still go in the job script by hand. Examples: an account to charge '
          '(--account), a QoS, or modules to load.\n'
          '\n'
          'Clusters that start machines when a job comes (cloud):\n'
          'On a cloud cluster (for example SLURM on Azure CycleCloud), machines are off until a job needs them. '
          "Detection still works: what the machines have (cores, memory, GPUs) is read from the scheduler's "
          'configuration, and those queues show machines start when a job comes. If that configuration cannot be '
          'read, the queue says so and you check memory and GPUs by hand. The first job of a queue, including the '
          'test job, waits a few minutes while a machine starts.\n'
          '\n'
          'At installation. When hosts.conf has no queues set up yet, the installer does the same detection and '
          'writes the result. The previous file is kept as hosts.conf.before-detect.\n'
          '\n'
          'In scipionapi doctor. The Queues line warns when:\n'
          '\n'
          '- a scheduler is installed but not set up;\n'
          '- a configured queue no longer exists in the scheduler;\n'
          '- queues are configured but the server has no scheduler commands.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#set-it-up-automatically'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'General host configuration',
  'text': 'The general section defines the identity and basic behavior of the execution host.\n'
          '\n'
          'Typical fields include:\n'
          '\n'
          '- host name or display name\n'
          '- whether the host is mandatory\n'
          '- submit prefix or job naming prefix\n'
          '- parallel command used by Scipion when MPI-style execution is required\n'
          '- general metadata used by the execution backend\n'
          '\n'
          'A common Scipion-style parallel command is:\n'
          '\n'
          'ini\n'
          'mpirun -np %(JOBNODES)d %(COMMAND)s\n'
          '\n'
          'The important point is that ScipionWeb does not hardcode the scheduler behavior. Instead, it keeps the '
          'scheduler-specific logic in the Host settings.\n'
          '\n'
          'This same Host name can also route Celery dispatch:\n'
          'In a Multi-Node Cluster Deployment, the Host name configured here can additionally be mapped to a Celery '
          'queue name so protocols using that Host are dispatched straight to a specific worker node — see '
          'Multi-Node Task Routing. This is independent of, and does not require, SLURM. A node joined with '
          'install.sh --join   --queue protocols-gpu --host gpu-nodes creates the Host gpu-nodes and its mapping for '
          "you: users then pick gpu-nodes in the protocol's form. ➡️ Several Machines",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#general-host-configuration'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Submit configuration',
  'text': 'The submit section defines how ScipionWeb talks to the queue system.\n'
          '\n'
          'Submit configuration with scheduler commands and job script template.\n'
          '\n'
          'For SLURM, the key command values are usually:\n'
          '\n'
          '| Field | Value |\n'
          '| --- | --- |\n'
          '| Submit command | sbatch --parsable %(JOBSCRIPT)s |\n'
          '| Cancel command | scancel %(JOBID)s |\n'
          '| Check command | squeue -h -j %(JOBID)s |\n'
          '| Submit prefix | scipion |\n'
          '\n'
          'The submit template is the script body that ScipionWeb generates for each protocol run. It usually '
          'contains scheduler directives, output/error file locations, resource requests, optional environment '
          'activation, and finally the protocol command.\n'
          '\n'
          'A simplified SLURM submit template looks like this:\n'
          '\n'
          'bash\n'
          '!/bin/bash\n'
          'SBATCH --export=ALL\n'
          'SBATCH -J %(JOBNAME)s\n'
          'SBATCH -o %(JOBSCRIPT)s.out\n'
          'SBATCH -e %(JOBSCRIPT)s.err\n'
          'SBATCH --open-mode=append\n'
          'SBATCH -p %(JOBQUEUE)s\n'
          'SBATCH --time=%(JOBTIME)s:00:00\n'
          'SBATCH --ntasks=%(JOBNODES)d\n'
          'SBATCH --cpus-per-task=%(JOBTHREADS)d\n'
          'SBATCH --mem=%(JOBMEMORY)s\n'
          '\n'
          '%(JOBCOMMAND)s\n'
          '\n'
          'Use sbatch --parsable when possible because it returns a cleaner SLURM job id, which is easier for '
          'ScipionWeb to track.\n'
          '\n'
          'Activate the correct environment when needed:\n'
          'If a queued job fails with No module named pyworkflow, the scheduler is probably running the job outside '
          'the expected Scipion Python environment. Add the required conda or environment activation before '
          '%(JOBCOMMAND)s in the submit template.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#submit-configuration'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Queue configuration',
  'text': 'The queue section defines which queues are available and which resource parameters users can choose when '
          'launching protocols.\n'
          '\n'
          'Queue configuration with user-facing resource fields.\n'
          '\n'
          'A queue definition normally maps a queue name to a list of parameters. Each parameter defines:\n'
          '\n'
          '- the internal key used in the submit template\n'
          '- the default value\n'
          '- the label shown to the user\n'
          '- the help text shown in the UI\n'
          '\n'
          'Example CPU queue fields:\n'
          '\n'
          '| Queue | Key | Default | Label | Help text |\n'
          '| --- | --- | --- | --- | --- |\n'
          '| debug | JOBMEMORY | 8192 | Memory (MB) | Select memory in megabytes |\n'
          '| debug | JOBTIME | 2 | Time (hours) | Select expected time in hours |\n'
          '\n'
          'The queue name must match the scheduler partition or queue name used in the submit template. For SLURM, '
          'if the submit template uses:\n'
          '\n'
          'bash\n'
          'SBATCH -p %(JOBQUEUE)s\n'
          '\n'
          'then JOBQUEUE should correspond to an existing SLURM partition, such as debug, cpu, gpu, or the '
          'site-specific partition name.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#queue-configuration'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'SLURM overview',
  'text': 'SLURM is a workload manager used to submit and manage jobs in a queue. In a minimal single-node setup, '
          'the same machine acts as both controller and compute node.\n'
          '\n'
          'This is useful for:\n'
          '\n'
          '- development and testing\n'
          '- reproducing queue execution issues\n'
          '- validating Scipion queue integration before using a larger cluster\n'
          '- local CPU/GPU scheduling on a workstation or server\n'
          '\n'
          'A typical single-node SLURM stack includes:\n'
          '\n'
          '- munge for authentication between SLURM daemons\n'
          '- slurmctld as the controller daemon\n'
          '- slurmd as the compute-node daemon\n'
          '- sbatch to submit jobs\n'
          '- squeue to monitor jobs\n'
          '- scancel to cancel jobs\n'
          '- optional GRES configuration for GPU scheduling',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#slurm-overview'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Install SLURM packages',
  'text': 'On Ubuntu or Debian-like systems, install SLURM and MUNGE with:\n'
          '\n'
          'bash\n'
          'sudo apt update\n'
          'sudo apt install -y munge slurm-wlm slurm-client\n'
          '\n'
          'Then confirm that the main commands are available:\n'
          '\n'
          'bash\n'
          'which sbatch\n'
          'which squeue\n'
          'which scancel\n'
          'which slurmd\n'
          'which slurmctld\n'
          '\n'
          'Some older distributions may use /etc/slurm-llnl/ instead of /etc/slurm/ for configuration files.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#install-slurm-packages'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Enable MUNGE',
  'text': 'MUNGE must be running before SLURM services can operate correctly.\n'
          '\n'
          'bash\n'
          'sudo systemctl enable munge\n'
          'sudo systemctl restart munge\n'
          'munge -n | unmunge\n'
          '\n'
          'The last command should decode a MUNGE credential without errors.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#enable-munge'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Collect node information',
  'text': 'Use the short hostname and SLURM hardware autodetection to prepare the node definition.\n'
          '\n'
          'bash\n'
          'hostname -s\n'
          'slurmd -C\n'
          '\n'
          'Example output:\n'
          '\n'
          'text\n'
          'myhost\n'
          'NodeName=myhost CPUs=16 Boards=1 SocketsPerBoard=1 CoresPerSocket=8 ThreadsPerCore=2 RealMemory=31800\n'
          '\n'
          'Use the values from your real machine. Do not copy CPU, memory, socket, or thread values from examples '
          'without checking your own host.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#collect-node-information'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Create runtime directories',
  'text': 'Create spool and log directories and assign ownership to the slurm user.\n'
          '\n'
          'bash\n'
          'sudo mkdir -p /var/spool/slurmd\n'
          'sudo mkdir -p /var/spool/slurmctld\n'
          'sudo mkdir -p /var/log/slurm\n'
          'getent passwd slurm\n'
          'sudo chown -R slurm:slurm /var/spool/slurmd\n'
          'sudo chown -R slurm:slurm /var/spool/slurmctld\n'
          'sudo chown -R slurm:slurm /var/log/slurm\n'
          '\n'
          'It is normal for the slurm user to have /usr/sbin/nologin as its shell.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#create-runtime-directories'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Minimal CPU-only SLURM configuration',
  'text': 'The main SLURM configuration file is usually:\n'
          '\n'
          'text\n'
          '/etc/slurm/slurm.conf\n'
          '\n'
          'A minimal CPU-only single-node configuration can look like this:\n'
          '\n'
          'ini\n'
          'ClusterName=localcluster\n'
          'SlurmctldHost=myhost\n'
          'SlurmUser=slurm\n'
          'AuthType=auth/munge\n'
          'MpiDefault=none\n'
          'ProctrackType=proctrack/linuxproc\n'
          'ReturnToService=2\n'
          'SlurmctldPidFile=/run/slurmctld.pid\n'
          'SlurmdPidFile=/run/slurmd.pid\n'
          'SlurmdSpoolDir=/var/spool/slurmd\n'
          'StateSaveLocation=/var/spool/slurmctld\n'
          'SwitchType=switch/none\n'
          'TaskPlugin=task/affinity\n'
          'SchedulerType=sched/backfill\n'
          'SelectType=select/constres\n'
          'SelectTypeParameters=CRCoreMemory\n'
          'AccountingStorageType=accountingstorage/none\n'
          'JobCompType=jobcomp/none\n'
          'JobAcctGatherType=jobacctgather/none\n'
          'SlurmctldDebug=info\n'
          'SlurmdDebug=info\n'
          '\n'
          'NodeName=myhost CPUs=16 Boards=1 SocketsPerBoard=1 CoresPerSocket=8 ThreadsPerCore=2 RealMemory=31800 '
          'State=UNKNOWN\n'
          'PartitionName=debug Nodes=myhost Default=YES MaxTime=INFINITE State=UP\n'
          '\n'
          'Replace myhost with hostname -s, and replace the hardware values with the output from slurmd -C.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#minimal-cpu-only-slurm-configuration'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Add GPU support with GRES',
  'text': 'GPU scheduling in SLURM is configured through GRES.\n'
          '\n'
          'First confirm that the operating system sees the GPU:\n'
          '\n'
          'bash\n'
          'nvidia-smi -L\n'
          'ls -lh /dev/nvidia\n'
          '\n'
          'For one NVIDIA GPU, create or edit:\n'
          '\n'
          'text\n'
          '/etc/slurm/gres.conf\n'
          '\n'
          'Example:\n'
          '\n'
          'ini\n'
          'NodeName=myhost Name=gpu File=/dev/nvidia0\n'
          '\n'
          'For two GPUs:\n'
          '\n'
          'ini\n'
          'NodeName=myhost Name=gpu File=/dev/nvidia0\n'
          'NodeName=myhost Name=gpu File=/dev/nvidia1\n'
          '\n'
          'Set safe ownership and permissions:\n'
          '\n'
          'bash\n'
          'sudo chown root:root /etc/slurm/gres.conf\n'
          'sudo chmod 644 /etc/slurm/gres.conf\n'
          '\n'
          'Then add the global GRES type to slurm.conf:\n'
          '\n'
          'ini\n'
          'GresTypes=gpu\n'
          '\n'
          'And add the GPU count to the node line:\n'
          '\n'
          'ini\n'
          'NodeName=myhost CPUs=16 Boards=1 SocketsPerBoard=1 CoresPerSocket=8 ThreadsPerCore=2 RealMemory=31800 '
          'Gres=gpu:1 State=UNKNOWN\n'
          '\n'
          'Validate GRES detection with:\n'
          '\n'
          'bash\n'
          'sudo slurmd -G\n'
          'sudo slurmd -C\n'
          '\n'
          'A valid slurmd -G output should report the GPU file, for example /dev/nvidia0.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#add-gpu-support-with-gres'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Start and verify SLURM services',
  'text': 'After editing slurm.conf or gres.conf, restart the services.\n'
          '\n'
          'bash\n'
          'sudo systemctl restart munge\n'
          'sudo systemctl restart slurmctld\n'
          'sudo systemctl restart slurmd\n'
          '\n'
          'Enable them at boot:\n'
          '\n'
          'bash\n'
          'sudo systemctl enable munge\n'
          'sudo systemctl enable slurmctld\n'
          'sudo systemctl enable slurmd\n'
          '\n'
          'Check service status:\n'
          '\n'
          'bash\n'
          'systemctl status munge --no-pager\n'
          'systemctl status slurmctld --no-pager\n'
          'systemctl status slurmd --no-pager\n'
          '\n'
          'Run basic health checks:\n'
          '\n'
          'bash\n'
          'scontrol ping\n'
          'sinfo\n'
          'sinfo -o "%P %N %G %t"\n'
          'scontrol show node myhost | grep -E "State=|Reason=|Gres="\n'
          '\n'
          'If the node is drained after fixing a problem, clear the drain state:\n'
          '\n'
          'bash\n'
          'sudo scontrol update NodeName=myhost State=UNDRAIN\n'
          '\n'
          'Some SLURM versions reject State=RESUME; use State=UNDRAIN in that case.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#start-and-verify-slurm-services'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Validate SLURM before connecting ScipionWeb',
  'text': 'Before configuring ScipionWeb, validate SLURM directly with small CPU and GPU jobs.\n'
          '\n'
          'CPU test:\n'
          '\n'
          'bash\n'
          'cat > /tmp/testslurmcpu.sh   /tmp/testslurmgpu.sh   Host\n'
          '5. run a small Scipion protocol through the queue',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#validate-slurm-before-connecting-scipionweb'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Configure ScipionWeb for a CPU SLURM queue',
  'text': 'Configure this from Settings > Host in the ScipionWeb interface. The goal is to enter the SLURM commands, '
          'the submit template, and the queue fields in the web form. Manual editing of hosts.conf is not required '
          'for this workflow.\n'
          '\n'
          'General section\n'
          '\n'
          '| Field | Recommended value |\n'
          '| --- | --- |\n'
          '| Name | SLURM |\n'
          '| Mandatory | False, unless every protocol must use this host |\n'
          '| Parallel command | mpirun -np %(JOBNODES)d %(COMMAND)s |\n'
          '| Submit prefix | scipion |\n'
          '\n'
          'Submit section\n'
          '\n'
          '| Field | Recommended value |\n'
          '| --- | --- |\n'
          '| Submit command | sbatch --parsable %(JOBSCRIPT)s |\n'
          '| Cancel command | scancel %(JOBID)s |\n'
          '| Check command | squeue -h -j %(JOBID)s |\n'
          '\n'
          'Submit template:\n'
          '\n'
          'bash\n'
          '!/bin/bash\n'
          'Inherit all current environment variables\n'
          'SBATCH --export=ALL\n'
          'Job name\n'
          'SBATCH -J %(JOBNAME)s\n'
          'Outputs\n'
          'SBATCH -o %(JOBSCRIPT)s.out\n'
          'SBATCH -e %(JOBSCRIPT)s.err\n'
          'SBATCH --open-mode=append\n'
          'Partition name\n'
          'SBATCH -p %(JOBQUEUE)s\n'
          'Resources\n'
          'SBATCH --time=%(JOBTIME)s:00:00\n'
          'SBATCH --ntasks=%(JOBNODES)d\n'
          'SBATCH --cpus-per-task=%(JOBTHREADS)d\n'
          'SBATCH --mem=%(JOBMEMORY)s\n'
          '\n'
          '%(JOBCOMMAND)s\n'
          '\n'
          'Queue section\n'
          '\n'
          'Create a queue entry whose name matches the SLURM partition, for example debug.\n'
          '\n'
          '| Key | Default | Label | Help text |\n'
          '| --- | --- | --- | --- |\n'
          '| JOBMEMORY | 8192 | Memory (MB) | Select memory in megabytes |\n'
          '| JOBTIME | 2 | Time (hours) | Select expected time in hours |\n'
          '\n'
          'After saving the Host settings, launch a small Scipion protocol and verify that ScipionWeb submits the '
          'job with sbatch, receives a job id, and tracks the job with squeue.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#configure-scipionweb-for-a-cpu-slurm-queue'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Configure ScipionWeb for a GPU SLURM queue',
  'text': 'Configure GPU execution from Settings > Host as well. The only difference from the CPU setup is that the '
          'submit template must request GPU resources, and the queue section should expose a GPU parameter.\n'
          '\n'
          'Before configuring this in ScipionWeb, confirm that SLURM already detects GPUs correctly with sudo slurmd '
          '-G, sinfo -o "%P %N %G %t", and a manual GPU sbatch test.\n'
          '\n'
          'General and submit commands\n'
          '\n'
          'Use the same general values and SLURM commands as the CPU setup:\n'
          '\n'
          '| Field | Recommended value |\n'
          '| --- | --- |\n'
          '| Submit command | sbatch --parsable %(JOBSCRIPT)s |\n'
          '| Cancel command | scancel %(JOBID)s |\n'
          '| Check command | squeue -h -j %(JOBID)s |\n'
          '\n'
          'GPU submit template:\n'
          '\n'
          'bash\n'
          '!/bin/bash\n'
          'Inherit all current environment variables\n'
          'SBATCH --export=ALL\n'
          'Job name\n'
          'SBATCH -J %(JOBNAME)s\n'
          'Outputs\n'
          'SBATCH -o %(JOBSCRIPT)s.out\n'
          'SBATCH -e %(JOBSCRIPT)s.err\n'
          'SBATCH --open-mode=append\n'
          'Partition name\n'
          'SBATCH -p %(JOBQUEUE)s\n'
          'Resources\n'
          'SBATCH --time=%(JOBTIME)s:00:00\n'
          'SBATCH --ntasks=%(JOBNODES)d\n'
          'SBATCH --cpus-per-task=%(JOBTHREADS)d\n'
          'SBATCH --mem=%(JOBMEMORY)s\n'
          'SBATCH --gres=gpu:%(GPUCOUNT)s\n'
          '\n'
          '%(JOBCOMMAND)s\n'
          '\n'
          'Queue section\n'
          '\n'
          'Create or update the queue entry in the Host queue form. For a debug partition with GPU support, use '
          'fields like:\n'
          '\n'
          '| Key | Default | Label | Help text |\n'
          '| --- | --- | --- | --- |\n'
          '| JOBMEMORY | 8192 | Memory (MB) | Select memory in megabytes |\n'
          '| JOBTIME | 2 | Time (hours) | Select expected time in hours |\n'
          '| GPUCOUNT | 1 | Number of GPUs | Select number of GPUs |\n'
          '\n'
          'Make sure the queue name matches the real SLURM partition and that the node actually reports the '
          'requested GPU resources in sinfo and scontrol show node.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#configure-scipionweb-for-a-gpu-slurm-queue'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Monitor jobs',
  'text': 'Useful commands while validating queued execution:\n'
          '\n'
          'bash\n'
          'squeue\n'
          'watch -n 1 squeue\n'
          'watch -n 1 \'squeue -o "%.10i %.9P %.30j %.8u %.2t %.10M %.6D %.20b %R"\'\n'
          'watch -n 1 \'sinfo -o "%P %N %G %t"\'\n'
          'scontrol show job   | grep -i tres\n'
          'watch -n 1 nvidia-smi\n'
          '\n'
          'A job can request gpu:1 and still show little or no GPU activity if the application has not reached a '
          'CUDA-heavy step yet.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#monitor-jobs'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Logs and troubleshooting',
  'text': 'Inspect SLURM daemon logs with:\n'
          '\n'
          'bash\n'
          'journalctl -u slurmctld -n 100 --no-pager\n'
          'journalctl -u slurmd -n 100 --no-pager\n'
          'journalctl -u slurmctld -f\n'
          'journalctl -u slurmd -f\n'
          '\n'
          'If physical log files are configured, check:\n'
          '\n'
          'bash\n'
          'ls -lh /var/log/slurm/\n'
          'sudo find /var/log -iname "slurm"\n'
          'grep -i log /etc/slurm/slurm.conf\n'
          '\n'
          'Common issues:\n'
          '\n'
          '| Symptom | Likely cause | Action |\n'
          '| --- | --- | --- |\n'
          '| Requested node configuration is not available | Job asks for resources the node does not provide, often '
          'GPU/GRES | Check #SBATCH --gres, sinfo -o "%P %N %G %t", and scontrol show node |\n'
          '| GRES/GPU count is lower than configured | slurm.conf declares GPUs but slurmd detects fewer devices | '
          'Check /etc/slurm/gres.conf, /dev/nvidia0, nvidia-smi -L, and sudo slurmd -G |\n'
          '| Node is DOWN or DRAINED | Previous configuration error or failed health check | Fix the cause, restart '
          'services, then run sudo scontrol update NodeName=myhost State=UNDRAIN |\n'
          '| Invalid node state specified | The SLURM version may not accept RESUME | Use State=UNDRAIN |\n'
          '| No module named pyworkflow | Job is using the wrong Python environment under SLURM | Activate the '
          'Scipion environment in the submit template before %(JOBCOMMAND)s |',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#logs-and-troubleshooting'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Practical checklist',
  'text': 'Before considering the Host configuration ready, verify:\n'
          '\n'
          '- SLURM services are running\n'
          '- sinfo shows the expected partition\n'
          '- CPU jobs can be submitted manually with sbatch\n'
          '- GPU jobs can be submitted manually if GPU execution is required\n'
          '- sbatch --parsable returns a clean job id\n'
          '- squeue -h -j   works for status checks\n'
          '- scancel   cancels jobs correctly\n'
          '- the Scipion Python environment is available inside submitted jobs\n'
          '- the queue names in ScipionWeb match real SLURM partitions\n'
          '- the resource keys in the queue section match placeholders in the submit template\n'
          '- a small Scipion protocol can run through the configured queue',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#practical-checklist'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'Good practice',
  'text': '- start with a simple CPU queue before adding GPU support\n'
          '- keep queue names aligned with real scheduler partitions\n'
          '- expose only the resource fields users actually need\n'
          '- use sensible defaults for memory, time, and GPU count\n'
          '- configure Host settings from the web interface instead of manually editing hosts.conf\n'
          '- keep the submit template readable and documented\n'
          '- validate scheduler commands outside ScipionWeb before debugging ScipionWeb itself\n'
          '- document site-specific queue policies for shared installations',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#good-practice'},
 {'area': 'user-guide',
  'page': 'Hosts and Queues',
  'title': 'When to use this configuration',
  'text': 'Use Host and Queue settings when:\n'
          '\n'
          '- multiple users submit protocols to the same server\n'
          '- protocol execution should be controlled by a scheduler\n'
          '- GPU resources need explicit reservation\n'
          '- long-running jobs should be visible in a queue\n'
          '- administrators need central control over memory, time, CPU, and GPU requests\n'
          '- ScipionWeb must integrate with an existing SLURM installation\n'
          '\n'
          'For simple local development without queue scheduling, a minimal local execution setup may be enough. For '
          'shared production environments, a queue-backed Host configuration is strongly recommended.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#when-to-use-this-configuration'},
 {'area': 'user-guide',
  'page': 'Outputs and Viewers',
  'title': 'Typical output workflow',
  'text': 'After a protocol finishes, you will usually:\n'
          '\n'
          '1. locate the generated outputs in the protocol card, protocol details, or output area\n'
          '2. confirm that the protocol finished successfully\n'
          '3. open the relevant preview or viewer\n'
          '4. inspect the data in the context of the project and protocol history\n'
          '5. decide whether a downstream protocol can use that output',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#typical-output-workflow'},
 {'area': 'user-guide',
  'page': 'Outputs and Viewers',
  'title': 'Open an output',
  'text': '1. Open the project that contains the protocol run.\n'
          '2. Locate the protocol that produced the result.\n'
          '3. Check that the protocol status is finished or otherwise suitable for inspection.\n'
          '4. Locate the output you want to review.\n'
          '5. Open the preview or viewer action associated with that output.\n'
          '6. Confirm that the viewer content matches the expected output type.\n'
          '\n'
          'Outputs can be opened from the project context using the available viewer actions.\n'
          '\n'
          'Before assuming a viewer is broken, confirm that:\n'
          '\n'
          '- the protocol completed successfully\n'
          '- the selected output belongs to the expected run\n'
          '- the viewer matches the output type\n'
          '- browser and backend requests are succeeding',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#open-an-output'},
 {'area': 'user-guide',
  'page': 'Outputs and Viewers',
  'title': 'Common viewer expectations',
  'text': 'Different output types may open different viewers or previews.\n'
          '\n'
          'Typical examples include:\n'
          '\n'
          '- metadata tables or galleries\n'
          '- volume viewers\n'
          '- coordinate viewers\n'
          '- tilt-series viewers\n'
          '- CTF tomography viewers\n'
          '- generic file previews\n'
          '\n'
          'Metadata outputs can be inspected in a table-oriented viewer.\n'
          '\n'
          'The exact viewer depends on the output class and the backend data available for that output.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#common-viewer-expectations'},
 {'area': 'user-guide',
  'page': 'Outputs and Viewers',
  'title': 'Desktop viewers from another computer',
  'text': 'Some outputs can also be opened in a desktop viewer (for example, a volume in ChimeraX). When you work '
          'from another computer and the server allows it, the viewer runs on the server and appears in a floating '
          'window inside ScipionWeb. The data stays on the server and you install nothing.\n'
          '\n'
          '- Move and resize the floating window as any other; the program follows its size.\n'
          '- Close the floating window to close the program, or close the program from its own menu.\n'
          '- If you reload the page, the viewers you had open come back.\n'
          '- You can have up to 3 viewers open. A viewer you do not use for 15 minutes is closed.\n'
          '\n'
          'If your administrator has not enabled this (see Desktop Viewers in the Browser), the viewer opens on the '
          "server's screen instead.",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#desktop-viewers-from-another-computer'},
 {'area': 'user-guide',
  'page': 'Outputs and Viewers',
  'title': 'While inspecting results',
  'text': 'Review outputs with these questions in mind:\n'
          '\n'
          '- is this the expected result for the current workflow step?\n'
          '- does the output belong to the intended protocol execution?\n'
          '- are there obvious signs that the run failed or produced incomplete data?\n'
          '- do follow-up protocols now have the inputs they need?\n'
          '\n'
          'Outputs are most useful when interpreted as part of a workflow, not as isolated files detached from the '
          'protocol history.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#while-inspecting-results'},
 {'area': 'user-guide',
  'page': 'Outputs and Viewers',
  'title': 'Use outputs as downstream inputs',
  'text': 'Before selecting an output as input for another protocol:\n'
          '\n'
          '1. verify that the output belongs to the intended project and protocol run\n'
          '2. inspect it if the output type has a useful viewer\n'
          '3. confirm that the output type is compatible with the downstream protocol parameter\n'
          '4. avoid selecting similarly named outputs from older runs by mistake\n'
          '\n'
          'This is especially important in projects with repeated runs, duplicated protocols, or several similar '
          'outputs.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#use-outputs-as-downstream-inputs'},
 {'area': 'user-guide',
  'page': 'Outputs and Viewers',
  'title': 'If a viewer does not open',
  'text': 'Check the following first:\n'
          '\n'
          '- failed browser network requests\n'
          '- missing backend viewer data\n'
          '- stale frontend state after route changes\n'
          '- incomplete protocol execution\n'
          '- whether the selected output still corresponds to the visible protocol state\n'
          '\n'
          'Useful recovery steps:\n'
          '\n'
          '1. refresh the project view\n'
          '2. reopen the protocol details\n'
          '3. try the viewer again\n'
          '4. inspect browser network errors\n'
          '5. check API logs if the viewer request fails server-side',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#if-a-viewer-does-not-open'},
 {'area': 'user-guide',
  'page': 'Outputs and Viewers',
  'title': 'Good practice',
  'text': 'When possible:\n'
          '\n'
          '- review outputs soon after execution finishes\n'
          '- compare what you see with what the workflow stage should produce\n'
          '- confirm that downstream steps are using the intended outputs\n'
          '- avoid relying only on memory when multiple similar runs exist in the same project',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#good-practice'},
 {'area': 'user-guide',
  'page': 'Plugins',
  'title': 'Typical plugin-related tasks',
  'text': 'In normal use, you may need to:\n'
          '\n'
          '- review available plugins\n'
          '- check whether a plugin is already installed\n'
          '- start an installation or removal flow\n'
          '- monitor plugin-related task progress\n'
          '- confirm that the UI reflects the new plugin state',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/plugins/#typical-plugin-related-tasks'},
 {'area': 'user-guide',
  'page': 'Plugins',
  'title': 'What to verify before changing plugin state',
  'text': '- you are working in the intended environment\n'
          '- the backend and worker are running correctly\n'
          '- Valkey and Celery are healthy\n'
          '- the plugin action is allowed for your role or workflow\n'
          '- you understand whether the change affects only your current workflow or the whole instance',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/plugins/#what-to-verify-before-changing-plugin-state'},
 {'area': 'user-guide',
  'page': 'Plugins',
  'title': 'During plugin operations',
  'text': 'Pay attention to:\n'
          '\n'
          '- task status changes\n'
          '- installation or removal logs\n'
          '- whether the plugin becomes available only after backend reload or restart\n'
          '- whether the final UI state matches the reported backend result\n'
          '\n'
          'Environment awareness:\n'
          'Plugin actions are especially easy to misread when local, staging, and production environments do not all '
          'have the same plugin state.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/plugins/#during-plugin-operations'},
 {'area': 'user-guide',
  'page': 'Plugins',
  'title': 'Common plugin pitfalls',
  'text': 'Problems often appear when:\n'
          '\n'
          '- the UI shows stale plugin state after a change\n'
          '- the worker is unhealthy even though the API is reachable\n'
          '- environment-specific dependencies break an installation flow\n'
          '- a user assumes a plugin is globally available because it was available elsewhere',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/plugins/#common-plugin-pitfalls'},
 {'area': 'user-guide',
  'page': 'Plugins',
  'title': 'If a plugin operation gets stuck',
  'text': 'Check:\n'
          '\n'
          '- worker logs\n'
          '- Valkey availability\n'
          '- task status endpoint responses\n'
          '- whether the plugin introduced environment-specific dependency issues\n'
          '- whether the final state requires a refresh, restart, or explicit reload of backend-managed data',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/plugins/#if-a-plugin-operation-gets-stuck'},
 {'area': 'user-guide',
  'page': 'Projects',
  'title': 'Typical project workflow',
  'text': 'A common project-oriented flow looks like this:\n'
          '\n'
          '1. open the Projects page\n'
          '2. create or open the intended project\n'
          '3. confirm the project identity and scope\n'
          '4. review visible protocols and outputs\n'
          '5. perform the next workflow action from the correct project context\n'
          '6. share the project if collaboration is needed',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/projects/#typical-project-workflow'},
 {'area': 'user-guide',
  'page': 'Projects',
  'title': 'Create a project',
  'text': '1. Open the Projects page.\n'
          '2. Select New Project.\n'
          '3. Enter a short but descriptive project name.\n'
          '4. Add a description if your team uses descriptions to document project purpose.\n'
          '5. Confirm the creation action.\n'
          '6. Open the new project and verify that the project page loads correctly.\n'
          '\n'
          'New project dialog used to create a project workspace.\n'
          '\n'
          'After creating a project, confirm:\n'
          '\n'
          '- the project appears in the project list\n'
          '- the name is easy to distinguish from similar projects\n'
          '- the project opens without API or authentication errors',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/projects/#create-a-project'},
 {'area': 'user-guide',
  'page': 'Projects',
  'title': 'Open an existing project',
  'text': '1. Open the Projects page.\n'
          '2. Locate the intended project card or list entry.\n'
          '3. Check the project name, description, thumbnail, or recent status before opening it.\n'
          '4. Open the project.\n'
          '5. Review the visible workflow before launching or editing anything.\n'
          '\n'
          'Project workflow view where protocols, status, and workflow context are reviewed.\n'
          '\n'
          'Verify these basics first:\n'
          '\n'
          '- project name and description match the expected workflow\n'
          '- visible protocols correspond to the intended dataset or experiment\n'
          '- current status and recent outputs look reasonable\n'
          '- you are not accidentally working in a similarly named project\n'
          '\n'
          'This matters because many later actions depend on being in the right project context before launching, '
          'reviewing, or sharing anything.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/projects/#open-an-existing-project'},
 {'area': 'user-guide',
  'page': 'Projects',
  'title': 'Rename a project',
  'text': 'Use rename when the project remains relevant but its label needs clarification.\n'
          '\n'
          '1. Open the project actions menu.\n'
          '2. Select the rename action.\n'
          '3. Enter the new project name.\n'
          '4. Confirm the change.\n'
          '5. Refresh or revisit the project list if the old name still appears temporarily.\n'
          '\n'
          'Before renaming, confirm:\n'
          '\n'
          '- no teammate is actively depending on the previous name\n'
          '- the new name follows your team convention\n'
          '- the rename is being applied in the intended environment',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/projects/#rename-a-project'},
 {'area': 'user-guide',
  'page': 'Projects',
  'title': 'Share a project',
  'text': '1. Open the project actions menu.\n'
          '2. Select the share action.\n'
          '3. Choose the target user or collaborator according to the available sharing UI.\n'
          '4. Confirm the sharing action.\n'
          '5. Ask the collaborator to refresh their project list if the project does not appear immediately.\n'
          '\n'
          'Shared work needs coordination:\n'
          'In collaborative environments, project-level actions should be treated as workflow changes, not just '
          'cosmetic edits.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/projects/#share-a-project'},
 {'area': 'user-guide',
  'page': 'Projects',
  'title': 'Project hygiene recommendations',
  'text': '- keep names consistent\n'
          '- avoid near-duplicate project labels\n'
          '- review old projects deliberately instead of letting them accumulate without context\n'
          '- document collaboration expectations when the same project is shared by several users\n'
          '- prefer clarity over short-lived convenience in naming and organization',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/projects/#project-hygiene-recommendations'},
 {'area': 'user-guide',
  'page': 'Projects',
  'title': 'If a project action fails',
  'text': 'Check:\n'
          '\n'
          '- whether you are still authenticated\n'
          '- whether the project list refreshes correctly\n'
          '- whether browser requests are failing with auth or CORS errors\n'
          '- whether the backend API returns validation or permission errors\n'
          '- whether you are looking at stale UI state after a route change\n'
          '\n'
          'Useful recovery steps:\n'
          '\n'
          '1. refresh the project list\n'
          '2. log out and log in again if authentication looks stale\n'
          '3. inspect failed browser network requests\n'
          '4. check API logs if the backend returns an error',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/projects/#if-a-project-action-fails'},
 {'area': 'user-guide',
  'page': 'Protocol Execution',
  'title': 'Common workflow',
  'text': 'A standard protocol workflow usually looks like this:\n'
          '\n'
          '1. open the relevant project\n'
          '2. choose the protocol to configure\n'
          '3. review required parameters and inputs\n'
          '4. save configuration changes intentionally\n'
          '5. launch the protocol\n'
          '6. monitor execution state and logs\n'
          '7. inspect outputs when execution finishes',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/protocols/#common-workflow'},
 {'area': 'user-guide',
  'page': 'Protocol Execution',
  'title': 'Open and configure a protocol',
  'text': '1. Open the intended project.\n'
          '2. Locate the protocol in the workflow view.\n'
          '3. Open the protocol form or details panel.\n'
          '4. Review required parameters first.\n'
          '5. Select inputs deliberately, especially pointer-like parameters that refer to outputs from previous '
          'protocols.\n'
          '6. Review optional parameters only after the required inputs are correct.\n'
          '\n'
          'Protocol form showing configurable parameters and input fields.\n'
          '\n'
          'Before changing values, confirm that you are editing the intended protocol run and not a similarly named '
          'one.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/protocols/#open-and-configure-a-protocol'},
 {'area': 'user-guide',
  'page': 'Protocol Execution',
  'title': 'Save before launching',
  'text': 'If the form separates saving from execution, treat Save and Execute as different actions:\n'
          '\n'
          '1. Change parameter values.\n'
          '2. Save the protocol configuration.\n'
          '3. Confirm that validation errors, if any, are resolved.\n'
          '4. Launch only after the saved values represent the run you want.\n'
          '\n'
          'Saved configuration vs execution:\n'
          'A protocol can be configured without being launched. Likewise, visible outputs may belong to a previous '
          'execution if a new launch has not finished yet.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/protocols/#save-before-launching'},
 {'area': 'user-guide',
  'page': 'Protocol Execution',
  'title': 'Before launch',
  'text': 'Confirm these points first:\n'
          '\n'
          '- the project context is the correct one\n'
          '- required inputs are available\n'
          '- parameter values were reviewed deliberately\n'
          '- previous protocol state does not conflict with the next run\n'
          '- you understand whether you are configuring, saving, or launching\n'
          '\n'
          'A careful pre-launch check is often the difference between a clean workflow and a confusing rerun later.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/protocols/#before-launch'},
 {'area': 'user-guide',
  'page': 'Protocol Execution',
  'title': 'Launch and monitor execution',
  'text': '1. Start execution from the protocol action or form.\n'
          '2. Watch the protocol status.\n'
          '3. Open logs when available.\n'
          '4. Keep an eye on progress indicators and error messages.\n'
          '5. Refresh the project view if status appears stale.\n'
          '\n'
          'Protocol logs help users confirm what happened during execution.\n'
          '\n'
          'During execution, pay attention to:\n'
          '\n'
          '- status changes\n'
          '- progress indicators\n'
          '- visible log output\n'
          '- whether the workflow remains responsive in the browser\n'
          '\n'
          'If the UI state does not update, refresh the project view and confirm the backend requests are '
          'succeeding.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/protocols/#launch-and-monitor-execution'},
 {'area': 'user-guide',
  'page': 'Protocol Execution',
  'title': 'After execution',
  'text': 'Once the protocol finishes, review:\n'
          '\n'
          '- final status\n'
          '- generated outputs\n'
          '- whether the expected viewer or output action is available\n'
          '- whether another downstream step is now unlocked\n'
          '- whether the result matches what the workflow stage should have produced\n'
          '\n'
          'A good habit is to inspect outputs before launching dependent downstream protocols.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/protocols/#after-execution'},
 {'area': 'user-guide',
  'page': 'Protocol Execution',
  'title': 'Common sources of confusion',
  'text': 'Users often confuse these states:\n'
          '\n'
          '- parameters changed but not saved\n'
          '- configuration saved but launch not triggered yet\n'
          '- execution started but the worker has not processed the task yet\n'
          '- execution finished but outputs not reviewed yet\n'
          '- visible outputs belong to an earlier run rather than the latest one\n'
          '\n'
          'Whenever something feels inconsistent, go back to the project context and verify the full protocol '
          'lifecycle again.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/protocols/#common-sources-of-confusion'},
 {'area': 'user-guide',
  'page': 'Protocol Execution',
  'title': 'If execution does not behave as expected',
  'text': 'Check:\n'
          '\n'
          '- browser network errors\n'
          '- backend and worker logs\n'
          '- Valkey and Celery health\n'
          '- whether the protocol parameters were saved correctly before launch\n'
          '- whether you are looking at the correct protocol run and project state\n'
          '\n'
          'Useful checks for administrators or developers:\n'
          '\n'
          './scripts/scipionapi status\n'
          './scripts/scipionapi logs\n'
          'valkey-cli ping\n'
          '\n'
          'If tasks remain pending, see Known Issues and Workarounds.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/protocols/#if-execution-does-not-behave-as-expected'},
 {'area': 'user-guide',
  'page': 'Settings',
  'title': 'What Settings is for',
  'text': 'Settings is not only a place for personal preferences. In ScipionWeb, it can also expose shared '
          'configuration that affects project organization, plugin integration, and how protocols are submitted for '
          'execution.\n'
          '\n'
          'Depending on your role and deployment, Settings may include:\n'
          '\n'
          '- user preferences\n'
          '- instance-level configuration\n'
          '- project tag management\n'
          '- environment variables for plugins and external software\n'
          '- host and queue configuration for protocol execution\n'
          '- advanced configuration views for administrators\n'
          '\n'
          'Some settings affect all users:\n'
          'Before changing instance, environment, host, or queue settings, confirm whether the change affects only '
          'your account or the whole ScipionWeb deployment.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/settings/#what-settings-is-for'},
 {'area': 'user-guide',
  'page': 'Settings',
  'title': 'Main settings areas',
  'text': 'User settings\n'
          '\n'
          'User settings usually affect your own experience in ScipionWeb.\n'
          '\n'
          'They may include preferences such as workflow display behavior, UI options, refresh intervals, or other '
          'per-user defaults.\n'
          '\n'
          'Change user settings when you want to adapt the interface to how you work, without changing how protocols '
          'run for everyone else.\n'
          '\n'
          'Instance settings\n'
          '\n'
          'Instance settings affect the ScipionWeb deployment as a whole.\n'
          '\n'
          'They may control runtime behavior, global defaults, or administrative options that should remain '
          'consistent across users.\n'
          '\n'
          'Only change instance settings when you understand the deployment impact and can validate the result '
          'afterward.\n'
          '\n'
          'Max concurrent runs per user limits how many protocols one user runs at the same time on the server.\n'
          '\n'
          '- 0, the default, means no limit. Set a limit only on a server shared by several groups without a queue '
          'system (with SLURM, the queue already shares out the resources).\n'
          "- Protocols launched together count as one: Run all, Continue all or a facility session's processing.\n"
          '- Streaming protocols that are still receiving data never count. An import watching its folder, or a '
          'protocol whose input protocol is still running, spends most of its time waiting for data; counting them '
          'would hold a streaming chain in launched for the whole session.\n'
          '- A protocol waiting for a slot stays in launched. Its status reads "launched · waiting for a run slot", '
          'with how many of your protocols are running and the limit. It starts by itself when one of them ends.\n'
          '\n'
          'Tags\n'
          '\n'
          'Tags help users organize protocols visually inside a project. They can be used to mark workflow stages, '
          'review status, candidate results, deprecated branches, or any team-specific classification.\n'
          '\n'
          'Use the dedicated guide when you need to create, edit, delete, or assign tags:\n'
          '\n'
          'Open the Tags guide\n'
          '\n'
          'Environment variables\n'
          '\n'
          'Environment variables managed from Settings are useful when ScipionWeb needs to expose runtime values to '
          'plugins or external software.\n'
          '\n'
          'A common case is when an external program is already installed on the server, and the plugin only needs a '
          'path variable such as PLUGINHOME pointing to that installation.\n'
          '\n'
          'Use the dedicated guide when you need to add or modify runtime variables from the web interface:\n'
          '\n'
          'Open the Environment Variables guide\n'
          '\n'
          'Hosts and queues\n'
          '\n'
          'Host settings define how ScipionWeb submits protocol executions, checks job status, and cancels jobs when '
          'a queue system is used.\n'
          '\n'
          'This is where SLURM-related queue execution can be configured from the web interface, including submit '
          'commands, cancel commands, check commands, submit templates, queues, memory, time, CPU, and GPU '
          'parameters.\n'
          '\n'
          'Use the dedicated guide when you need to configure protocol execution through SLURM or another queue '
          'system:\n'
          '\n'
          'Open the Hosts and Queues guide\n'
          '\n'
          'Users, roles, groups, audit and usage (administrators)\n'
          '\n'
          'These tabs appear only to whoever holds the permission each needs:\n'
          '\n'
          '| Tab | Permission | What it is for |\n'
          '|---|---|---|\n'
          '| Users | users.manage | Activate new accounts (they start inactive), give them roles and groups |\n'
          '| Roles | roles.manage | Create roles and choose their permissions; Administrator holds them all |\n'
          "| Groups | groups.manage | Labs: members, PIs, and what PIs may do in their members' projects |\n"
          '| Audit | audit.view | Who did what: sign-ins, accounts, sharing, settings, plugins |\n'
          '| Usage | storage.view | How much disk and computing each user, group and project takes |\n'
          '\n'
          'Usage has two parts: Disk and Computing.\n'
          '\n'
          'Disk answers "who is filling the disk?":\n'
          '\n'
          "- The figures. The free space of the projects' disk. Tables by user, by group and by project, largest "
          'first; click a user to see their projects.\n'
          '- Cleanup candidates. Projects not used for three months are marked.\n'
          '- How it is measured.\n'
          '- ScipionWeb measures each project in the background, slowly so it does not load the disk: once a day, an '
          "hour after a protocol changes it, and whenever you press Measure all again or a project's ruler button.\n"
          "- Imported movies are usually links to the microscope's data, so they are not counted.\n"
          '- A user in two groups counts in both.\n'
          '\n'
          'Computing answers "who is using the machines?":\n'
          '\n'
          '- The period. This week, this month, last month, the last 30 days, this year, or a range of days.\n'
          '- The figures.\n'
          '- GPU hours, run hours, runs and failed runs.\n'
          '- Tables by user, by group, by protocol and by machine, most GPU hours first.\n'
          '- Click a user to see their runs: project, protocol, start, hours, GPUs, machine, queue job and status.\n'
          '- The runs running now.\n'
          '- Export CSV saves the table shown.\n'
          '- How it is counted.\n'
          '- ScipionWeb records each run when it starts and when it ends, with the user who launched it.\n'
          '- Run hours are the time a run ran inside the period. GPU hours are those hours times the GPUs the run '
          'was given, whether it kept them busy or not.\n'
          '- With a queue (SLURM…), the run is recorded where the job ran, with its job id.\n'
          '- A run whose worker stopped (a machine restarted, a killed process) counts until its last sign of life, '
          'a minute before at most.\n'
          '- Only runs launched since this version are counted.\n'
          '\n'
          'Each user also sees, at the top of the Projects page, what their own projects take and what they ran this '
          'month.\n'
          '\n'
          'Advanced configuration\n'
          '\n'
          'Some deployments may expose advanced or read-only configuration views.\n'
          '\n'
          'Use these sections carefully. They are useful for reviewing the current state, debugging configuration '
          'issues, or confirming what ScipionWeb has loaded, but they may not be intended for routine editing by all '
          'users.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/settings/#main-settings-areas'},
 {'area': 'user-guide',
  'page': 'Settings',
  'title': 'Recommended workflow before changing settings',
  'text': 'Before changing anything, confirm:\n'
          '\n'
          '1. which area you are changing\n'
          '2. whether the change is personal, project-level, runtime-level, queue-level, or instance-wide\n'
          '3. whether other users may be affected\n'
          '4. how you will validate the change\n'
          '5. how to revert the change if the result is not correct\n'
          '\n'
          'This is especially important for environment variables and host/queue settings, because they can affect '
          'plugin discovery and protocol execution.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/settings/#recommended-workflow-before-changing-settings'},
 {'area': 'user-guide',
  'page': 'Settings',
  'title': 'Validation after changes',
  'text': 'After saving settings, validate the smallest possible workflow that proves the change worked.\n'
          '\n'
          'Examples:\n'
          '\n'
          '- after changing a user preference, refresh the affected view\n'
          '- after editing tags, open a project and confirm that tag assignment still works\n'
          '- after changing an environment variable, open or run a plugin protocol that depends on it\n'
          '- after changing host or queue settings, launch a small protocol through the configured queue\n'
          '- after changing instance settings, verify that the expected behavior is visible for the intended users',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/settings/#validation-after-changes'},
 {'area': 'user-guide',
  'page': 'Settings',
  'title': 'Good practice',
  'text': '- change one setting at a time\n'
          '- save and validate before making another change\n'
          '- document shared conventions for tags, environment variables, and queues\n'
          '- avoid changing host or queue settings while protocols are being launched or debugged\n'
          '- avoid changing runtime paths without validating the affected plugin\n'
          '- keep queue names aligned with the real scheduler configuration\n'
          '- prefer clear names and conservative defaults over ad-hoc values',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/settings/#good-practice'},
 {'area': 'user-guide',
  'page': 'Settings',
  'title': 'Common settings mistakes',
  'text': 'Users often run into trouble when they:\n'
          '\n'
          '- assume a setting is personal when it is shared\n'
          '- change several settings before validating any of them\n'
          '- forget to refresh the affected page after saving\n'
          '- edit a runtime variable but test the wrong plugin or project\n'
          '- configure a queue name that does not exist in the scheduler\n'
          '- change a submit template without checking the generated job script behavior\n'
          '- modify settings in a test deployment and expect production to change',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/settings/#common-settings-mistakes'},
 {'area': 'user-guide',
  'page': 'Settings',
  'title': 'If a settings change does not persist',
  'text': 'Check:\n'
          '\n'
          '- whether the save request succeeded\n'
          '- whether the page reloaded stale data\n'
          '- whether your user role has permission to change that section\n'
          '- whether browser or API errors appeared during save\n'
          '- whether another source of configuration is overriding the expected value\n'
          '- whether the backend logs show a validation or permission error\n'
          '\n'
          'Useful recovery steps:\n'
          '\n'
          '1. refresh the Settings page\n'
          '2. confirm that the value is still present\n'
          '3. validate with the smallest affected workflow\n'
          '4. inspect browser network requests if the value disappears\n'
          '5. check backend logs if the API reports an error',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/settings/#if-a-settings-change-does-not-persist'},
 {'area': 'user-guide',
  'page': 'Sharing and Collaboration',
  'title': 'Typical sharing workflow',
  'text': 'A common collaboration flow usually includes:\n'
          '\n'
          '1. confirming the correct project is selected\n'
          '2. granting access to the intended teammate\n'
          '3. verifying that the collaborator can open the project\n'
          '4. keeping naming and ownership expectations clear',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sharing/#typical-sharing-workflow'},
 {'area': 'user-guide',
  'page': 'Sharing and Collaboration',
  'title': 'Before sharing a project',
  'text': 'Check these basics first:\n'
          '\n'
          '- you are in the intended environment\n'
          '- the project is really the one meant for collaboration\n'
          '- the target user exists in the same instance\n'
          '- your team agrees on how project changes will be coordinated',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sharing/#before-sharing-a-project'},
 {'area': 'user-guide',
  'page': 'Sharing and Collaboration',
  'title': 'Good collaboration practices',
  'text': '- share only the projects that actually need collaboration\n'
          '- keep project names stable and descriptive\n'
          '- avoid ambiguity about who is responsible for operational changes\n'
          '- communicate before high-impact changes in shared projects\n'
          '- make it clear which outputs or workflow stages are already validated\n'
          '\n'
          'Shared context matters:\n'
          'Collaboration works better when teammates do not need to guess which project state is considered current '
          'or trustworthy.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sharing/#good-collaboration-practices'},
 {'area': 'user-guide',
  'page': 'Sharing and Collaboration',
  'title': 'Common collaboration pitfalls',
  'text': 'Problems often appear when:\n'
          '\n'
          '- a similarly named project is shared by mistake\n'
          '- two users assume different workflow stages are current\n'
          '- high-impact actions happen without coordination\n'
          '- one user is working in a different environment than the others',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sharing/#common-collaboration-pitfalls'},
 {'area': 'user-guide',
  'page': 'Sharing and Collaboration',
  'title': 'If sharing does not work as expected',
  'text': 'Check:\n'
          '\n'
          '- whether the intended user exists in the instance\n'
          '- whether the share action completed successfully\n'
          '- whether the collaborator is logged into the correct environment\n'
          '- whether browser requests return auth or permission errors\n'
          '- whether stale session state is hiding recent permission changes',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sharing/#if-sharing-does-not-work-as-expected'},
 {'area': 'user-guide',
  'page': 'Sign Up',
  'title': 'When to use sign-up',
  'text': 'Use the sign-up form when:\n'
          '\n'
          '- you are accessing a ScipionWeb instance for the first time\n'
          '- an administrator has asked you to create your own user account\n'
          '- your institution or team uses self-registration for new users\n'
          '\n'
          'If you already have credentials, go directly to First Login and Session Basics.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#when-to-use-sign-up'},
 {'area': 'user-guide',
  'page': 'Sign Up',
  'title': 'Open the sign-up page',
  'text': 'From the login screen, choose the sign-up option to open the registration form.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#open-the-sign-up-page'},
 {'area': 'user-guide',
  'page': 'Sign Up',
  'title': 'Fill in your account details',
  'text': 'Complete the required fields in the form. Depending on the instance configuration, the form may request '
          'information such as:\n'
          '\n'
          '- username\n'
          '- email address\n'
          '- password\n'
          '- password confirmation\n'
          '\n'
          'Use an email address that administrators can recognize, especially on shared facilities or institutional '
          'deployments.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#fill-in-your-account-details'},
 {'area': 'user-guide',
  'page': 'Sign Up',
  'title': 'Submit the form',
  'text': 'After submitting the form, the account is created immediately. You can then continue to the login page '
          'and sign in with the credentials you just registered.\n'
          '\n'
          'If registration is disabled or restricted on a specific deployment, the form will not be available or the '
          'request may be rejected. In that case, contact the instance administrator.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#submit-the-form'},
 {'area': 'user-guide',
  'page': 'Sign Up',
  'title': 'After creating the account',
  'text': 'Continue with:\n'
          '\n'
          '1. First Login and Session Basics\n'
          '2. Projects\n'
          '3. Protocol Execution\n'
          '\n'
          'The first successful login confirms that the account is valid and that the browser session was created '
          'correctly.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#after-creating-the-account'},
 {'area': 'user-guide',
  'page': 'Sign Up',
  'title': 'Common sign-up problems',
  'text': 'The sign-up option is not visible\n'
          '\n'
          'The instance may not allow self-registration. Contact the administrator and ask whether accounts are '
          'created manually.\n'
          '\n'
          'The email or username is already in use\n'
          '\n'
          'Try signing in with the existing account. If you do not remember the credentials, ask the administrator '
          'for help.\n'
          '\n'
          'The password is rejected\n'
          '\n'
          'Check the password rules shown by the form. Some deployments may enforce minimum length or other password '
          'requirements.\n'
          '\n'
          'The account was created but login fails\n'
          '\n'
          'Confirm that you are using the same username or email address and password that you registered. If the '
          'problem persists, ask the administrator to verify that the account exists and that the backend is '
          'reachable.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#common-sign-up-problems'},
 {'area': 'user-guide',
  'page': 'Sign Up',
  'title': 'Good practices',
  'text': '- Use a recognizable username or email address.\n'
          '- Do not share accounts between users.\n'
          '- Keep your password private.\n'
          '- Confirm that you are signing up on the intended ScipionWeb instance.\n'
          '- Use separate accounts for local, staging, and production instances when required.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#good-practices'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'What tags are for',
  'text': 'Tags are project-level labels that can be attached to protocols. A tag usually combines:\n'
          '\n'
          '- a short title\n'
          '- an optional description\n'
          '- a color that makes the label easy to recognize\n'
          '\n'
          'They are intended to make large workflows easier to scan without changing the protocol execution itself.\n'
          '\n'
          'Good tag examples include:\n'
          '\n'
          '- preprocessing\n'
          '- review needed\n'
          '- particles\n'
          '- tomo\n'
          '- final candidate\n'
          '- deprecated',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#what-tags-are-for'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'Typical tag workflow',
  'text': 'A common workflow looks like this:\n'
          '\n'
          '1. open the relevant project\n'
          '2. open the tag management area\n'
          '3. create the tags your project needs\n'
          '4. assign tags to protocols from the workflow view\n'
          '5. use the visible labels to understand the project structure faster\n'
          '6. update or remove tags when the project convention changes',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#typical-tag-workflow'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'Open the tag manager',
  'text': 'The tag manager is where the available tags for a project are maintained.\n'
          '\n'
          'Depending on the ScipionWeb deployment and your permissions, you may find it from the project-related '
          'settings area or from a tag management action in the interface.\n'
          '\n'
          'Before editing tags, confirm:\n'
          '\n'
          '- you are working in the intended project\n'
          '- the tag convention is shared with collaborators if the project is shared\n'
          '- the tag name is clear enough to be understood later\n'
          '- the color is visually distinct from existing tags\n'
          '\n'
          'Tags organize the workflow:\n'
          'Tags help users read and group protocols visually. They do not replace protocol parameters, execution '
          'status, outputs, or project permissions.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#open-the-tag-manager'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'Create a new tag',
  'text': '1. Open the tag manager.\n'
          '2. Select the action to create a new tag.\n'
          '3. Enter a short title.\n'
          '4. Add a description if the meaning may not be obvious to other users.\n'
          '5. Choose a color.\n'
          '6. Save the tag.\n'
          '7. Confirm that the new tag appears in the tag list.\n'
          '\n'
          'New tag dialog used to define the title, description, and color of a tag.\n'
          '\n'
          'A good tag title should be short enough to fit comfortably on protocol cards while still being '
          'meaningful.\n'
          '\n'
          'Recommended naming habits:\n'
          '\n'
          '- use clear names instead of abbreviations only one person understands\n'
          '- avoid creating several tags that mean nearly the same thing\n'
          '- reserve colors for meaning, not decoration\n'
          '- keep descriptions focused on when the tag should be used',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#create-a-new-tag'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'Edit or delete existing tags',
  'text': 'Use editing when the tag is still useful but its name, description, or color needs improvement.\n'
          '\n'
          'Use deletion only when the tag is no longer part of the project convention.\n'
          '\n'
          'Before deleting a tag, check whether it is already assigned to protocols. Removing a tag can make the '
          'workflow harder to interpret if collaborators were using it as part of their review process.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#edit-or-delete-existing-tags'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'Assign tags to protocols',
  'text': 'Tags become useful when they are assigned to protocol cards in the project workflow.\n'
          '\n'
          'A typical assignment flow is:\n'
          '\n'
          '1. open the project workflow view\n'
          '2. locate the protocol or protocols you want to classify\n'
          '3. open the protocol action menu or tag assignment area\n'
          '4. select one or more tags\n'
          '5. confirm that the selected tags appear on the protocol card\n'
          '\n'
          'Tag assignment from the protocol card or protocol action menu.\n'
          '\n'
          'When assigning tags, review whether the label describes the protocol itself, the current review status, '
          'or the role of the protocol inside the workflow. Mixing these meanings in the same tag set can make the '
          'workflow harder to read.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#assign-tags-to-protocols'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'Review tagged protocols',
  'text': 'After assigning tags, use them as visual cues while navigating the workflow.\n'
          '\n'
          'Tags can help you quickly identify:\n'
          '\n'
          '- protocols that belong to the same processing stage\n'
          '- protocols that need review\n'
          '- protocols that generated important outputs\n'
          '- protocols that should not be reused\n'
          '- alternative branches or candidate results\n'
          '\n'
          'In collaborative projects, tags are especially useful when combined with consistent project naming, '
          'comments, and clear communication about which protocols are considered final.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#review-tagged-protocols'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'Good practice',
  'text': '- define a small tag set first and expand only when needed\n'
          '- use colors consistently across related projects when possible\n'
          '- document team-specific meanings in tag descriptions\n'
          '- keep tag names short enough to remain readable on protocol cards\n'
          '- remove obsolete tags only after checking their current assignments\n'
          '- avoid using tags as a substitute for protocol comments or execution status',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#good-practice'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'Common sources of confusion',
  'text': 'Users often run into confusion when they:\n'
          '\n'
          '- create too many tags with overlapping meanings\n'
          '- use colors inconsistently\n'
          '- assign review-status tags and workflow-stage tags without a clear convention\n'
          '- assume a tag changes protocol execution behavior\n'
          '- delete a tag that collaborators were using to track project progress\n'
          '\n'
          'When a tag convention becomes unclear, simplify the tag list and agree on a small set of meanings before '
          'continuing.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#common-sources-of-confusion'},
 {'area': 'user-guide',
  'page': 'Tags',
  'title': 'If tags do not appear as expected',
  'text': 'Check:\n'
          '\n'
          '- whether you are working in the correct project\n'
          '- whether the tag was saved successfully\n'
          '- whether the protocol card has refreshed after assignment\n'
          '- whether your user role has permission to manage or assign tags\n'
          '- whether the browser shows failed API requests\n'
          '- whether another user changed the tag list while you were working\n'
          '\n'
          'Useful recovery steps:\n'
          '\n'
          '1. refresh the project view\n'
          '2. reopen the tag manager and confirm the tag still exists\n'
          '3. assign the tag again from the protocol menu\n'
          '4. check backend logs if the API reports an error',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#if-tags-do-not-appear-as-expected'},
 {'area': 'user-guide',
  'page': 'Working Efficiently',
  'title': '1. Confirm context before acting',
  'text': 'Before launching, sharing, renaming, or reviewing results, verify:\n'
          '\n'
          '- the environment you are using\n'
          '- the project you are in\n'
          '- the protocol or output you are looking at\n'
          '- whether the visible state belongs to the latest workflow step\n'
          '\n'
          'A large fraction of user confusion comes from acting in the wrong context rather than from a broken '
          'feature.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#1-confirm-context-before-acting'},
 {'area': 'user-guide',
  'page': 'Working Efficiently',
  'title': '2. Prefer clear naming over fast naming',
  'text': 'Use names that help you and your teammates answer basic questions quickly:\n'
          '\n'
          '- what is this project about?\n'
          '- which dataset or experiment does it represent?\n'
          '- is this the current workflow or an older attempt?\n'
          '\n'
          'Good names reduce mistakes later in protocol execution, sharing, and output review.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#2-prefer-clear-naming-over-fast-naming'},
 {'area': 'user-guide',
  'page': 'Working Efficiently',
  'title': '3. Treat save and launch as different moments',
  'text': 'A good mental model is:\n'
          '\n'
          '- configure carefully\n'
          '- save intentionally\n'
          '- launch only when the saved state is the one you want\n'
          '\n'
          'This helps avoid confusion about whether a protocol was merely edited or actually executed.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#3-treat-save-and-launch-as-different-moments'},
 {'area': 'user-guide',
  'page': 'Working Efficiently',
  'title': '4. Review outputs early',
  'text': 'Do not wait too long to inspect important outputs.\n'
          '\n'
          'Early review helps you detect:\n'
          '\n'
          '- incorrect input selection\n'
          '- unexpected parameter choices\n'
          '- runs that completed but produced the wrong kind of result\n'
          '- downstream steps that should not continue yet',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#4-review-outputs-early'},
 {'area': 'user-guide',
  'page': 'Working Efficiently',
  'title': '5. Coordinate shared work explicitly',
  'text': 'In collaborative environments:\n'
          '\n'
          '- communicate before high-impact project actions\n'
          '- make it clear which project state is current\n'
          '- avoid silent assumptions about who validated which outputs\n'
          '- keep naming and ownership conventions stable',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#5-coordinate-shared-work-explicitly'},
 {'area': 'user-guide',
  'page': 'Working Efficiently',
  'title': '6. Use the browser as a debugging surface',
  'text': 'When something feels inconsistent, inspect:\n'
          '\n'
          '- browser network requests\n'
          '- failed API responses\n'
          '- visible route or reload behavior\n'
          '- whether the page is showing stale state\n'
          '\n'
          'You do not need to be a backend developer to benefit from checking the browser first.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#6-use-the-browser-as-a-debugging-surface'},
 {'area': 'user-guide',
  'page': 'Working Efficiently',
  'title': '7. Recheck before assuming the system is wrong',
  'text': 'Before concluding that something failed, quickly verify:\n'
          '\n'
          '- session is still valid\n'
          '- the correct environment is open\n'
          '- the right project is selected\n'
          '- the expected protocol run is visible\n'
          '- the output belongs to the workflow step you think it does\n'
          '\n'
          'This habit saves a surprising amount of time.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#7-recheck-before-assuming-the-system-is-wrong'},
 {'area': 'installation',
  'page': 'Choose Your Setup',
  'title': 'One machine',
  'text': 'The usual case: one Linux machine runs the web, the database and the protocols.\n'
          '\n'
          'bash\n'
          'wget https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/install.sh\n'
          'chmod +x install.sh\n'
          './install.sh --check-only   # tells you what the machine is missing\n'
          './install.sh                # asks for the admin user and installs\n'
          '\n'
          'Then open the address it prints in a browser. ➡️ Guided Installation',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/choose-setup/#one-machine'},
 {'area': 'installation',
  'page': 'Choose Your Setup',
  'title': 'One machine, without Internet',
  'text': 'Copy the release files next to install.sh (from a USB stick, a shared folder…). The installer sees them '
          'and installs from there, without downloading anything:\n'
          '\n'
          'text\n'
          'my-folder/\n'
          '├── install.sh\n'
          '├── ScipionAPI-v4.0.0.zip\n'
          '├── ScipionWeb-v4.0.0-dist.zip\n'
          '└── manifest.json        (optional: adds checksum verification)\n'
          '\n'
          'bash\n'
          'cd my-folder\n'
          './install.sh\n'
          '\n'
          '➡️ Installing Without Internet',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/choose-setup/#one-machine-without-internet'},
 {'area': 'installation',
  'page': 'Choose Your Setup',
  'title': 'Several machines',
  'text': 'Does your cluster have SLURM?:\n'
          '- Yes: let SLURM run the protocols and share out the GPUs. Install ScipionWeb on one machine and create a '
          'host with a queue. ➡️ With SLURM\n'
          '- No: join your GPU machines as compute nodes, as below. The users choose the GPUs.\n'
          '\n'
          'One main node runs the web, the database and the job queue. Compute nodes take protocols from the queue '
          'and run them; the main node can leave all the computing to them (multinode compute off). They all see the '
          'same installation on a shared disk.\n'
          '\n'
          'text\n'
          '┌──────────── MAIN NODE ────────────┐\n'
          'browser ──────┤  web + API · PostgreSQL · Valkey  │\n'
          '└────────────────┬──────────────────┘\n'
          '│  job queue\n'
          '┌───────────────────┼───────────────────┐\n'
          '▼                   ▼                   ▼\n'
          '┌────────────┐      ┌────────────┐      ┌────────────┐\n'
          '│  node 1    │      │  node 2    │      │  GPU node  │\n'
          '│  protocols │      │  protocols │      │  protocols │\n'
          '└────────────┘      └────────────┘      └────────────┘\n'
          'all of them see the same installation (shared disk)\n'
          '\n'
          'bash\n'
          "1. On the main node (once): install it, then open it to the nodes' network\n"
          './install.sh\n'
          '~/scipionweb/scripts/scipionapi multinode enable --network 10.0.0.0/24\n'
          '\n'
          '2. On each compute node\n'
          './install.sh --join ~/scipionweb\n'
          '\n'
          '3. On the main node, once the nodes work: leave the computing to them\n'
          '~/scipionweb/scripts/scipionapi multinode compute off\n'
          '\n'
          '➡️ Several Machines (Multi-Node) · Example: a three-machine cluster, step by step',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/choose-setup/#several-machines'},
 {'area': 'installation',
  'page': 'Choose Your Setup',
  'title': 'What you need in every setup',
  'text': '- Linux, with sudo for the person installing\n'
          '- Conda (Miniconda is enough)\n'
          '- PostgreSQL and Valkey on the machine that runs the web (the main node)\n'
          '\n'
          './install.sh --check-only checks all of it and tells you exactly what to install. ➡️ Prerequisites',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/choose-setup/#what-you-need-in-every-setup'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': 'Overview',
  'text': 'A typical production deployment with systemd includes:\n'
          '\n'
          '1. Stop CLI-managed services (if running)\n'
          '2. Identify installation paths\n'
          '3. Create a systemd service for the API\n'
          '4. Create a systemd service for the Celery worker\n'
          '5. Reload systemd\n'
          '6. Enable services on boot\n'
          '7. Start services\n'
          '8. Verify status and logs\n'
          '\n'
          'Prerequisite:\n'
          'Make sure the installation is already working (for example via provision) before switching to systemd.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#overview'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': '1. Stop CLI-Managed Services',
  'text': 'If you previously started services with the ScipionAPI CLI, stop them first to avoid port conflicts and '
          'duplicate workers.\n'
          '\n'
          './scripts/scipionapi stop\n'
          '\n'
          'Avoid mixed process management:\n'
          'Do not run the same API/worker both through the CLI and systemd at the same time.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#1-stop-cli-managed-services'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': '2. Locate Installation Paths',
  'text': 'Identify the paths used by your deployment.\n'
          '\n'
          'Example API installation directory\n'
          '\n'
          'text\n'
          '/opt/scipionweb/ScipionAPI-1.0.0\n'
          '\n'
          'Example SCIPIONHOME\n'
          '\n'
          'text\n'
          '/opt/scipionweb/scipionhome\n'
          '\n'
          'Example Conda environment\n'
          '\n'
          'text\n'
          '/home/youruser/miniconda3/envs/scipion4Web\n'
          '\n'
          'Use absolute paths only:\n'
          'Always use absolute paths in systemd service files (WorkingDirectory, ExecStart, SCIPIONHOME, etc.).',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#2-locate-installation-paths'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': '3. Create the systemd Service for the API',
  'text': 'Create the service file:\n'
          '\n'
          'text\n'
          '/etc/systemd/system/scipionapi.service\n'
          '\n'
          'Example scipionapi.service\n'
          '\n'
          'ini\n'
          '[Unit]\n'
          'Description=ScipionAPI Service\n'
          'After=network.target postgresql.service valkey-server.service\n'
          'Wants=postgresql.service valkey-server.service\n'
          '\n'
          '[Service]\n'
          'Type=simple\n'
          'User=youruser\n'
          'WorkingDirectory=/opt/scipionweb/ScipionAPI-1.0.0\n'
          'Environment=SCIPIONHOME=/opt/scipionweb/scipionhome\n'
          'ExecStart=/home/youruser/miniconda3/envs/scipion4Web/bin/uvicorn app.backend.main:app --host 0.0.0.0 '
          '--port 8080\n'
          'Restart=always\n'
          'RestartSec=5\n'
          '\n'
          '[Install]\n'
          'WantedBy=multi-user.target\n'
          '\n'
          'Service dependencies:\n'
          'After= controls startup order. Wants= asks systemd to also start PostgreSQL and Valkey when starting the '
          'API service.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#3-create-the-systemd-service-for-the-api'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': '4. Create the systemd Service for the Celery Worker',
  'text': 'Create the service file:\n'
          '\n'
          'text\n'
          '/etc/systemd/system/scipion-celery.service\n'
          '\n'
          'Example scipion-celery.service\n'
          '\n'
          'ini\n'
          '[Unit]\n'
          'Description=ScipionAPI Celery Worker\n'
          'After=network.target valkey-server.service\n'
          'Wants=valkey-server.service\n'
          '\n'
          '[Service]\n'
          'Type=simple\n'
          'User=youruser\n'
          'WorkingDirectory=/opt/scipionweb/ScipionAPI-1.0.0\n'
          'Environment=SCIPIONHOME=/opt/scipionweb/scipionhome\n'
          'ExecStart=/home/youruser/miniconda3/envs/scipion4Web/bin/celery -A app.workers.taskqueue worker '
          '--loglevel=info\n'
          'Restart=always\n'
          'RestartSec=5\n'
          '\n'
          '[Install]\n'
          'WantedBy=multi-user.target\n'
          '\n'
          'Celery and API separation:\n'
          'Keeping the API and Celery worker in separate services makes restarts, monitoring, and troubleshooting '
          'much easier.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#4-create-the-systemd-service-for-the-celery-worker'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': '5. Reload systemd',
  'text': 'Reload the systemd daemon after creating or modifying service files:\n\nsudo systemctl daemon-reload',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#5-reload-systemd'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': '6. Enable Services on Boot',
  'text': 'Enable both services so they start automatically after reboot:\n'
          '\n'
          'sudo systemctl enable scipionapi\n'
          'sudo systemctl enable scipion-celery',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#6-enable-services-on-boot'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': '7. Start Services',
  'text': 'Start both services:\n'
          '\n'
          'sudo systemctl start scipionapi\n'
          'sudo systemctl start scipion-celery\n'
          '\n'
          'Start order:\n'
          'Start order between API and Celery is usually flexible, but Valkey must be available before the worker '
          'can process tasks.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#7-start-services'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': '8. Check Status',
  'text': 'Verify both services are active:\n'
          '\n'
          'sudo systemctl status scipionapi\n'
          'sudo systemctl status scipion-celery\n'
          '\n'
          'For a quick summary:\n'
          '\n'
          'systemctl is-active scipionapi\n'
          'systemctl is-active scipion-celery\n'
          '\n'
          'Expected output:\n'
          '\n'
          'text\n'
          'active\n'
          'active',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#8-check-status'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': 'Logs',
  'text': 'Follow logs in real time with journalctl:\n'
          '\n'
          'journalctl -u scipionapi -f\n'
          'journalctl -u scipion-celery -f\n'
          '\n'
          'Show recent logs only:\n'
          'Useful filters:\n'
          '\n'
          '- journalctl -u scipionapi -n 100 --no-pager\n'
          '- journalctl -u scipion-celery -n 100 --no-pager',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#logs'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': 'Optional: nginx Reverse Proxy',
  'text': 'Using nginx in front of ScipionAPI is recommended for:\n'
          '\n'
          '- HTTPS termination\n'
          '- Exposing ports 80 / 443\n'
          '- Reverse proxy headers\n'
          '- Load balancing (advanced setups)\n'
          '\n'
          'Minimal nginx proxy example\n'
          '\n'
          'nginx\n'
          'location / {\n'
          'proxypass http://127.0.0.1:8080;\n'
          'proxysetheader Host $host;\n'
          'proxysetheader X-Real-IP $remoteaddr;\n'
          'proxysetheader X-Forwarded-For $proxyaddxforwardedfor;\n'
          'proxysetheader X-Forwarded-Proto $scheme;\n'
          '}\n'
          '\n'
          'Integrated mode paths:\n'
          'If you use integrated mode (frontend served by the API) and custom API mount paths (for example /api), '
          'verify nginx forwards requests without breaking those routes.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#optional-nginx-reverse-proxy'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': 'Hardening and Operational Tips (Recommended)',
  'text': 'Run with a dedicated service user\n'
          '\n'
          'Instead of a personal account, consider a dedicated Linux user (for example scipion) to run the '
          'services.\n'
          '\n'
          'Restrict file permissions\n'
          '\n'
          'Protect:\n'
          '\n'
          '- SCIPIONHOME/.env\n'
          '- Logs (if they may contain sensitive paths or errors)\n'
          '- Project data directories\n'
          '\n'
          'Keep backups before upgrades\n'
          '\n'
          'Before upgrading ScipionAPI/ScipionWeb, backup:\n'
          '\n'
          '- PostgreSQL database\n'
          '- SCIPIONHOME/.env\n'
          '- Critical project data (if applicable)\n'
          '\n'
          'Test service restart behavior\n'
          '\n'
          'After deployment, verify service restarts:\n'
          '\n'
          'sudo systemctl restart scipionapi\n'
          'sudo systemctl restart scipion-celery\n'
          'sudo systemctl status scipionapi scipion-celery',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#hardening-and-operational-tips-recommended'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': 'Troubleshooting',
  'text': 'Service fails to start:\n'
          'Check:\n'
          '\n'
          '- WorkingDirectory exists\n'
          '- ExecStart points to the correct Conda environment binaries\n'
          '- SCIPIONHOME is correct\n'
          '- PostgreSQL and Valkey are running\n'
          '- The installation works when started manually\n'
          '\n'
          'ModuleNotFoundError in systemd logs:\n'
          'Usually caused by an incorrect WorkingDirectory or the wrong Python/Celery binary path in ExecStart.\n'
          '\n'
          'Port 8080 already in use:\n'
          'Another process is already bound to the port. Stop the conflicting process or change the API port.\n'
          '\n'
          'Celery starts but tasks do not run:\n'
          'Verify Valkey connectivity, broker URL configuration, and check worker logs for import/configuration '
          'errors.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#troubleshooting'},
 {'area': 'installation',
  'page': 'Production Deployment with systemd',
  'title': 'Summary',
  'text': 'Using systemd provides:\n'
          '\n'
          '- Automatic restart on failure\n'
          '- Startup on boot\n'
          '- Centralized logging with journalctl\n'
          '- Better operational stability for production deployments\n'
          '\n'
          'A minimal production setup typically includes:\n'
          '\n'
          '- scipionapi.service\n'
          '- scipion-celery.service\n'
          '- PostgreSQL\n'
          '- Valkey\n'
          '- nginx (recommended for HTTPS/public exposure)\n'
          '\n'
          '← Previous: Upgrade\n'
          '\n'
          'Next: Multi-Node Cluster Deployment →',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/deployment-systemd/#summary'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'Official download endpoint',
  'text': 'Published ScipionWeb release files live at:\n'
          '\n'
          'https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/\n'
          '\n'
          'The release endpoint normally contains:\n'
          '\n'
          'text\n'
          'install.sh\n'
          'manifest.json\n'
          'ScipionAPI-vX.Y.Z.zip\n'
          'ScipionWeb-vX.Y.Z-dist.zip\n'
          '\n'
          'manifest.json records the available releases, their matching API/Web artifacts, SHA256 metadata, and the '
          'version identified as latest.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#official-download-endpoint'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'Release artifact naming',
  'text': 'The standard filenames are:\n'
          '\n'
          'text\n'
          'ScipionAPI-vX.Y.Z.zip\n'
          'ScipionWeb-vX.Y.Z-dist.zip\n'
          '\n'
          'For example:\n'
          '\n'
          'text\n'
          'ScipionAPI-v4.0.1.zip\n'
          'ScipionWeb-v4.0.1-dist.zip\n'
          '\n'
          'Keep the API and Web artifacts on the same release version unless you are intentionally performing a '
          'compatibility test.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#release-artifact-naming'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'Recommended manual directory layout',
  'text': 'A simple local workspace can look like:\n'
          '\n'
          'text\n'
          '$HOME/scipionweb-manual/\n'
          '├── ScipionAPI-v4.0.1.zip\n'
          '└── ScipionWeb-v4.0.1-dist.zip\n'
          '\n'
          'After extracting the API ZIP:\n'
          '\n'
          'text\n'
          '$HOME/scipionweb-manual/\n'
          '├── ScipionAPI-v4.0.1.zip\n'
          '├── ScipionWeb-v4.0.1-dist.zip\n'
          '└──  /\n'
          '├── app/\n'
          '├── scipionapicli/\n'
          '├── scripts/\n'
          '├── alembic/\n'
          '├── pyproject.toml\n'
          '└── alembic.ini\n'
          '\n'
          'The Web ZIP can remain compressed and be passed directly to provision --web-dist.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#recommended-manual-directory-layout'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'Download a specific release',
  'text': 'Using wget\n'
          '\n'
          'bash\n'
          'mkdir -p "$HOME/scipionweb-manual"\n'
          'cd "$HOME/scipionweb-manual"\n'
          '\n'
          'wget "https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/ScipionAPI-v4.0.1.zip"\n'
          'wget "https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/ScipionWeb-v4.0.1-dist.zip"\n'
          '\n'
          'Using curl\n'
          '\n'
          'bash\n'
          'mkdir -p "$HOME/scipionweb-manual"\n'
          'cd "$HOME/scipionweb-manual"\n'
          '\n'
          'curl -O "https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/ScipionAPI-v4.0.1.zip"\n'
          'curl -O "https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/ScipionWeb-v4.0.1-dist.zip"',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#download-a-specific-release'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'Inspect the public manifest',
  'text': 'To see which release is currently marked as latest:\n'
          '\n'
          'bash\n'
          'curl -fsSL \\\n'
          'https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/manifest.json\n'
          '\n'
          'A release entry conceptually contains:\n'
          '\n'
          'json\n'
          '{\n'
          '"latest": "v4.0.1",\n'
          '"releases": {\n'
          '"v4.0.1": {\n'
          '"api": {\n'
          '"file": "ScipionAPI-v4.0.1.zip",\n'
          '"sha256": "...",\n'
          '"size": 123456\n'
          '},\n'
          '"web": {\n'
          '"file": "ScipionWeb-v4.0.1-dist.zip",\n'
          '"sha256": "...",\n'
          '"size": 654321\n'
          '}\n'
          '}\n'
          '}\n'
          '}\n'
          '\n'
          'The guided installer and updater use this metadata automatically.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#inspect-the-public-manifest'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'Verify checksums manually',
  'text': 'The normal guided installer verifies published SHA256 values automatically.\n'
          '\n'
          'For a manual bundle workflow, compare the downloaded files with the values in manifest.json:\n'
          '\n'
          'bash\n'
          'sha256sum ScipionAPI-v4.0.1.zip\n'
          'sha256sum ScipionWeb-v4.0.1-dist.zip\n'
          '\n'
          'Do not continue if the calculated checksum differs from the published checksum.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#verify-checksums-manually'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'Extract the API bundle',
  'text': 'bash\n'
          'unzip ScipionAPI-v4.0.1.zip\n'
          '\n'
          'The archive can either contain the API files at its root or inside one versioned directory. Locate the '
          'extracted ScipionAPI root and verify that it contains at least:\n'
          '\n'
          'text\n'
          'app/\n'
          'scipionapicli/\n'
          'scripts/scipionapi\n'
          'alembic/\n'
          'pyproject.toml\n'
          'alembic.ini\n'
          '\n'
          'Make the wrapper executable if required:\n'
          '\n'
          'bash\n'
          'chmod +x scripts/scipionapi',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#extract-the-api-bundle'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'Web bundle usage',
  'text': 'For integrated mode, the Web ZIP can be passed directly to provision:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi provision \\\n'
          '--user admin \\\n'
          '--email admin@example.org \\\n'
          '--web-dist /path/to/ScipionWeb-v4.0.1-dist.zip\n'
          '\n'
          'Manual extraction is optional. If you inspect the Web ZIP, its packaged content should resolve to a valid '
          'Vite dist directory containing the expected index.html and assets.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#web-bundle-usage'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'When this manual path is appropriate',
  'text': 'Use this workflow when:\n'
          '\n'
          '- validating release artifacts before publication\n'
          '- reproducing a packaging problem\n'
          '- installing from an offline/local artifact mirror\n'
          '- testing a specific API/Web bundle pair\n'
          '- building custom deployment automation around provision\n'
          '- hosting the frontend separately\n'
          '\n'
          'For ordinary end-user installation, prefer the Guided Installation.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#when-this-manual-path-is-appropriate'},
 {'area': 'installation',
  'page': 'Download and Extract Bundles',
  'title': 'Common mistakes',
  'text': 'Using mismatched API and Web versions:\n'
          'Normal releases are published as pairs. Keep the versions aligned.\n'
          '\n'
          'Skipping checksum verification in a manual install:\n'
          'The guided installer performs this automatically; a manual workflow must preserve the same trust boundary '
          'explicitly.\n'
          '\n'
          'Looking for scripts/scipionapi inside the Web ZIP:\n'
          'The wrapper belongs to the ScipionAPI bundle. The Web ZIP contains the compiled frontend.\n'
          '\n'
          'Treating this as the recommended new-user path:\n'
          'Manual downloading is supported, but install.sh is the normal installation entrypoint now.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/download-bundles/#common-mistakes'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': '1. Download the installer',
  'text': 'Download the small standalone installer from the public ScipionWeb release endpoint:\n'
          '\n'
          'bash\n'
          'wget https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/install.sh\n'
          'chmod +x install.sh\n'
          '\n'
          'install.sh is intentionally standalone. You do not need to download the API or Web ZIP files yourself for '
          'the normal installation path.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#1-download-the-installer'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': '2. Check the machine first',
  'text': 'Before installing anything, run the prerequisite check:\n'
          '\n'
          'bash\n'
          './install.sh --check-only\n'
          '\n'
          'The preflight validates the supported Linux runtime and checks the important installation dependencies '
          'together, including:\n'
          '\n'
          '- curl or wget\n'
          '- unzip\n'
          '- sudo\n'
          '- Conda and its base Python\n'
          '- PostgreSQL client/server access\n'
          '- Valkey client/server availability\n'
          '- local PostgreSQL administrative access through sudo -u postgres psql\n'
          '\n'
          'The installer does not automatically install missing system packages. If something is missing or '
          'misconfigured, it reports the problems and exits so the host can be fixed explicitly.\n'
          '\n'
          'Run the preflight first:\n'
          '--check-only is the fastest way to distinguish a host prerequisite problem from a ScipionWeb installation '
          'problem.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#2-check-the-machine-first'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': '3. Run the installer',
  'text': 'For the normal interactive installation:\n'
          '\n'
          'bash\n'
          './install.sh\n'
          '\n'
          'The installer asks for the required values, including:\n'
          '\n'
          '- installation directory\n'
          '- administrator username\n'
          '- administrator email\n'
          '- administrator password using a hidden prompt\n'
          '\n'
          'The default installation directory is:\n'
          '\n'
          'text\n'
          '$HOME/scipionweb\n'
          '\n'
          'The default release is latest.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#3-run-the-installer'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'What the installer does',
  'text': 'A normal run performs the following high-level sequence:\n'
          '\n'
          '1. validates system prerequisites\n'
          '2. validates the target installation directory\n'
          '3. downloads manifest.json from the public release server when available\n'
          '4. resolves latest or the requested release version\n'
          '5. downloads the matching ScipionAPI and ScipionWeb ZIP files\n'
          '6. verifies SHA256 checksums published in the manifest\n'
          '7. extracts ScipionAPI into the final installation directory\n'
          '8. delegates environment, database, migrations, Web deployment, and startup to scripts/scipionapi '
          'provision\n'
          '9. creates a .scipionweb-installation marker only after successful provisioning\n'
          '\n'
          'The API and Web artifacts therefore come from the same release entry in manifest.json.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#what-the-installer-does'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'Install a specific version',
  'text': 'To install a specific published release:\n'
          '\n'
          'bash\n'
          './install.sh --version v4.0.1\n'
          '\n'
          'Versions without the leading v are also normalized when valid:\n'
          '\n'
          'bash\n'
          './install.sh --version 4.0.1\n'
          '\n'
          'Use latest to follow the latest value published in manifest.json.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#install-a-specific-version'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'Choose another installation directory',
  'text': 'bash\n'
          './install.sh --install-dir /data/scipionweb\n'
          '\n'
          'The installer deliberately refuses unsafe or ambiguous targets. In particular, it will not silently '
          'install over an unrelated non-empty directory or an existing ScipionWeb installation.\n'
          '\n'
          'If an installation already exists, use its updater instead:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi update',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#choose-another-installation-directory'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'API/Web port selection',
  'text': 'You normally do not need to choose a port manually.\n'
          '\n'
          'When --api-port is omitted, provisioning preserves an existing APIPORT when appropriate or selects an '
          'available port automatically and stores it in the installation environment.\n'
          '\n'
          'To force a specific port:\n'
          '\n'
          'bash\n'
          './install.sh --api-port 39080\n'
          '\n'
          'After installation, inspect the persisted value with:\n'
          '\n'
          'bash\n'
          'grep \'^APIPORT=\' "$HOME/scipionweb/scipionhome/.env"\n'
          '\n'
          'Adjust the path if you selected a custom installation directory.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#apiweb-port-selection'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'Non-interactive installation',
  'text': 'For automation, provide the required values explicitly and supply the password through '
          'SCIPIONWEBADMINPASSWORD:\n'
          '\n'
          'bash\n'
          "export SCIPIONWEBADMINPASSWORD=' '\n"
          '\n'
          './install.sh \\\n'
          '--non-interactive \\\n'
          '--install-dir /data/scipionweb \\\n'
          '--user admin \\\n'
          '--email admin@example.org\n'
          '\n'
          'Useful environment equivalents include:\n'
          '\n'
          'text\n'
          'SCIPIONWEBINSTALLDIR\n'
          'SCIPIONWEBADMINUSER\n'
          'SCIPIONWEBADMINEMAIL\n'
          'SCIPIONWEBADMINPASSWORD\n'
          'SCIPIONWEBVERSION\n'
          'SCIPIONWEBDOWNLOADBASEURL\n'
          'SCIPIONWEBLOCALDIR\n'
          'SCIPIONWEBAPIPORT\n'
          'SCIPIONAPICONDAEXE\n'
          '\n'
          'Avoid placing real passwords directly in shell command arguments.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#non-interactive-installation'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'Install from the release files, without downloading',
  'text': "When ScipionAPI- .zip and ScipionWeb- -dist.zip (and optionally manifest.json) are in the installer's "
          'folder, or in the folder given with --local-dir, the installer uses them and downloads nothing:\n'
          '\n'
          'bash\n'
          './install.sh --local-dir /media/usb/scipionweb-v4.0.0\n'
          '\n'
          '➡️ Installing Without Internet',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#install-from-the-release-files-without-downloading'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'Add this machine as a compute node',
  'text': 'On a machine that should only run protocols for an existing installation (seen on a shared disk at the '
          'same path), --join installs nothing and joins it instead:\n'
          '\n'
          'bash\n'
          './install.sh --join /home/scipion/scipionweb\n'
          './install.sh --join /home/scipion/scipionweb --queue protocols-gpu --host gpu-nodes   # a GPU node\n'
          '\n'
          '| Option | Meaning |\n'
          '|---|---|\n'
          "| --join PATH | The main node's installation folder |\n"
          '| --queue NAME | The queue the node takes protocols from (default protocols) |\n'
          '| --concurrency N | Protocols at a time (default: its GPUs, or 4) |\n'
          "| --host NAME | The Scipion host whose protocols go to the node's queue |\n"
          '\n'
          '➡️ Several Machines (Multi-Node)',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#add-this-machine-as-a-compute-node'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'Verify the installation',
  'text': 'From the installed directory, run:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi status\n'
          './scripts/scipionapi doctor --quick\n'
          '\n'
          'To inspect the selected port:\n'
          '\n'
          'bash\n'
          "grep '^APIPORT=' scipionhome/.env\n"
          '\n'
          'For deeper troubleshooting:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi doctor\n'
          './scripts/scipionapi logs',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#verify-the-installation'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'Failed installation behavior',
  'text': 'If provisioning fails after installation has started, the installer preserves the installation directory '
          'for inspection instead of deleting potentially useful logs and state.\n'
          '\n'
          'Look under:\n'
          '\n'
          'text\n'
          '/scipionhome/logs/\n'
          '\n'
          'Fix the reported problem and then decide whether to retry or clean up the incomplete installation.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#failed-installation-behavior'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'Updating later',
  'text': 'A guided installation is updated from its installed ScipionAPI root:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --dry-run\n'
          './scripts/scipionapi update\n'
          '\n'
          'The updater preserves SCIPIONHOME, .env, projects, logs, and database data while replacing managed '
          'application files and the deployed Web bundle.\n'
          '\n'
          'See Upgrade / Reinstall Notes for details.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#updating-later'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'Completely removing a guided installation',
  'text': 'Preview the complete removal first. Run the command by absolute path so your shell is not left inside a '
          'directory that will be deleted:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall --full --dry-run\n'
          '\n'
          'Then, when the plan is correct:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall --full\n'
          '\n'
          '--full validates the guided installation marker, installation root, SCIPIONHOME, and expected ScipionAPI '
          'layout before destructive cleanup.\n'
          '\n'
          'See the uninstall CLI reference before using full removal on important systems.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#completely-removing-a-guided-installation'},
 {'area': 'installation',
  'page': 'Guided Installation',
  'title': 'When to use the manual paths instead',
  'text': 'Use the manual bundle/provision documentation when you intentionally need one of these scenarios:\n'
          '\n'
          '- API-only deployment\n'
          '- frontend hosted separately\n'
          '- custom or remote PostgreSQL setup\n'
          '- installation debugging\n'
          '- development environments\n'
          '- infrastructure-specific deployment automation\n'
          '\n'
          'For normal new installations, prefer:\n'
          '\n'
          '> Prerequisites → install.sh --check-only → install.sh',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/guided-install/#when-to-use-the-manual-paths-instead'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': 'Mental model',
  'text': 'Manual installation separates the layers that provision normally combines:\n'
          '\n'
          '1. Python/Conda environment\n'
          '2. database/runtime configuration\n'
          '3. migrations and administrator creation\n'
          '4. runtime startup and verification\n'
          '\n'
          'That makes this path slower, but useful when you need to inspect each layer independently.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#mental-model'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': '1. Prepare the ScipionAPI source/package',
  'text': 'Start from an extracted ScipionAPI release bundle or a development checkout, depending on the task.\n'
          '\n'
          'For a packaged release, verify that the root contains at least:\n'
          '\n'
          'text\n'
          'app/\n'
          'scipionapicli/\n'
          'scripts/scipionapi\n'
          'alembic/\n'
          'pyproject.toml\n'
          'alembic.ini',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#1-prepare-the-scipionapi-sourcepackage'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': '2. Create the Conda environment',
  'text': 'Example development/manual environment:\n'
          '\n'
          'bash\n'
          'conda create -n scipion4Web python=3.11 -y\n'
          'conda activate scipion4Web\n'
          'python -m pip install --upgrade pip',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#2-create-the-conda-environment'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': '3. Install dependencies',
  'text': 'bash\n'
          'pip install -r requirements.txt\n'
          'pip install -e .\n'
          'scipionapi --help\n'
          '\n'
          'For packaged operational installs, prefer the project wrapper/bootstrap path where possible because it '
          'keeps Conda/runtime handling aligned with the normal ScipionAPI lifecycle.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#3-install-dependencies'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': '4. Prepare PostgreSQL',
  'text': 'For a custom/manual database setup, create the PostgreSQL role and database through your normal '
          'administrative process.\n'
          '\n'
          'Make sure the values you create match the runtime configuration you will use later, especially:\n'
          '\n'
          'text\n'
          'DATABASEURL\n'
          'DATABASENAME\n'
          'DATABASEUSER\n'
          'DATABASEPASS\n'
          '\n'
          'Verify connectivity before applying migrations.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#4-prepare-postgresql'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': '5. Prepare `SCIPION_HOME`',
  'text': 'Example local workspace:\n'
          '\n'
          'bash\n'
          'mkdir -p scipionhome\n'
          'export SCIPIONHOME="$(pwd)/scipionhome"\n'
          '\n'
          'The persistent runtime configuration belongs at:\n'
          '\n'
          'text\n'
          '$SCIPIONHOME/.env\n'
          '\n'
          "Use the CLI's install command whenever possible to generate/align runtime state rather than "
          'hand-maintaining every key.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#5-prepare-scipion_home'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': '6. Configure/install runtime state',
  'text': 'Use the hidden password prompt:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi install \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org"\n'
          '\n'
          'Or, for automation:\n'
          '\n'
          'bash\n'
          "export SCIPIONAPIADMINPASSWORD=' '\n"
          '\n'
          './scripts/scipionapi install \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org" \\\n'
          '--password-env SCIPIONAPIADMINPASSWORD\n'
          '\n'
          'This keeps administrator passwords out of ordinary shell arguments.\n'
          '\n'
          'If you require a fixed API/Web port:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi install \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org" \\\n'
          '--api-port 39080\n'
          '\n'
          'Otherwise the installation can preserve an existing APIPORT or select a free port automatically and '
          'persist it in .env.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#6-configureinstall-runtime-state'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': '7. Migrations',
  'text': 'The supported install flow applies migrations as part of runtime setup.\n'
          '\n'
          'When debugging Alembic manually, load the intended environment first:\n'
          '\n'
          'bash\n'
          'set -a\n'
          'source "$SCIPIONHOME/.env"\n'
          'set +a\n'
          'alembic upgrade head\n'
          '\n'
          'Do this only when you intentionally need the lower-level migration step separate from install/provision.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#7-migrations'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': '8. Start services',
  'text': 'bash\n'
          './scripts/scipionapi start\n'
          './scripts/scipionapi status\n'
          '\n'
          'Resolve the actual configured port:\n'
          '\n'
          'bash\n'
          'APIPORT="$(grep \'^APIPORT=\' "$SCIPIONHOME/.env" | tail -n 1 | cut -d= -f2-)"\n'
          'echo "$APIPORT"\n'
          '\n'
          'Then verify health:\n'
          '\n'
          'bash\n'
          'curl "http://localhost:${APIPORT}/health"\n'
          '\n'
          'Do not assume port 8080 unless you explicitly configured that value.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#8-start-services'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': '9. Diagnostics',
  'text': 'bash\n'
          './scripts/scipionapi doctor --quick\n'
          './scripts/scipionapi doctor\n'
          './scripts/scipionapi logs\n'
          '\n'
          'For development/manual work, keeping API and worker logs visible can make startup and queue problems '
          'easier to diagnose.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#9-diagnostics'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': 'Adding the Web UI manually',
  'text': 'For an integrated deployment from a specific Web release bundle, the direct provision path is usually '
          'simpler than reproducing Web deployment by hand:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi provision \\\n'
          '--user admin \\\n'
          '--email admin@example.org \\\n'
          '--web-dist /path/to/ScipionWeb-vX.Y.Z-dist.zip\n'
          '\n'
          'See Provision and Integrated Mode.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#adding-the-web-ui-manually'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': 'When this path is best',
  'text': 'Manual installation is appropriate for:\n'
          '\n'
          '- development environments\n'
          '- CI/testing\n'
          '- remote PostgreSQL deployments\n'
          '- migration/debugging investigations\n'
          '- custom infrastructure\n'
          '- release-package validation\n'
          '\n'
          'For ordinary installations, the supported path remains:\n'
          '\n'
          'text\n'
          'Prerequisites → install.sh --check-only → install.sh',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#when-this-path-is-best'},
 {'area': 'installation',
  'page': 'Manual Installation',
  'title': 'Common mistakes',
  'text': 'Using a direct password argument:\n'
          'Prefer the hidden prompt or --password-env instead of putting real credentials in shell history.\n'
          '\n'
          'Assuming port 8080:\n'
          'Read the persisted APIPORT from .env unless you explicitly chose a fixed port.\n'
          '\n'
          'Database and .env disagree:\n'
          'Keep runtime database values aligned with the role/database you actually created.\n'
          '\n'
          'Starting only one side of the runtime:\n'
          'Verify both API and Celery/Valkey behavior with status, doctor, and logs.\n'
          '\n'
          'Using manual installation when a managed update is enough:\n'
          'For an existing packaged installation, use ./scripts/scipionapi update for normal version changes.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/manual-install/#common-mistakes'},
 {'area': 'installation',
  'page': 'Multi-Node Cluster Deployment',
  'title': 'Architecture Overview',
  'text': 'text\n'
          'Master node\n'
          '├── FastAPI / uvicorn (API + web UI)\n'
          '├── PostgreSQL\n'
          '├── Valkey (Celery broker)\n'
          '└── Plugin Celery worker\n'
          '\n'
          'Worker node 1                      Worker node 2                      Worker node 3\n'
          '└── Protocol Celery worker         └── Protocol Celery worker         └── Protocol Celery worker\n'
          'queue: protocols                   queue: protocols                   queue: protocols-gpu\n'
          '\n'
          "Every worker node points DATABASEURL / BROKERURL at the master's routable hostname (not localhost), and "
          'all nodes mount the same shared filesystem for scipionhome/projects.\n'
          '\n'
          'Only the master serves the web UI and REST API. Worker nodes never run uvicorn; they only run Celery '
          'workers that pull protocol-execution (and optionally plugin-install) tasks from the shared broker.\n'
          '\n'
          'Start smaller if you are unsure:\n'
          'If you only need to keep the API off the compute nodes, a single worker node already exercises this '
          'entire setup. Add the remaining nodes once the first one works end to end.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-cluster/#architecture-overview'},
 {'area': 'installation',
  'page': 'Multi-Node Cluster Deployment',
  'title': 'Prerequisites',
  'text': '- A shared filesystem mounted at the same path on every node (NFS or equivalent), holding at least '
          'scipionhome/projects. Sharing scipionhome/config too is strongly recommended so hosts.conf and '
          'celeryqueuerouting.json (see below) stay identical everywhere without manual copying.\n'
          '- PostgreSQL and Valkey reachable from every worker node over the network (not localhost).\n'
          '- The same ScipionAPI checkout and Conda environment installed independently on every node (code and the '
          'Python environment are not shared over NFS for performance reasons — only project data is).\n'
          '- The plugins each worker actually needs installed on that worker. A shared filesystem does not make a '
          'plugin "installed" on a node that never ran its installer.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-cluster/#prerequisites'},
 {'area': 'installation',
  'page': 'Multi-Node Cluster Deployment',
  'title': 'Step 1 — Master Setup',
  'text': 'Install ScipionAPI on the master exactly as in a normal single-node install (see Guided Installation or '
          'Manual Installation).\n'
          '\n'
          '1.1 Point .env at routable addresses\n'
          '\n'
          "Edit scipionhome/.env so DATABASEURL and BROKERURL use the master's LAN hostname or IP, not localhost / "
          '127.0.0.1:\n'
          '\n'
          'dotenv\n'
          'POSTGRESHOST=master.internal\n'
          'DATABASEURL=postgresql://scipionuser: @master.internal:5432/scipiondb\n'
          'BROKERURL=redis://: @master.internal:6379/0\n'
          '\n'
          'POSTGRESHOST is what the API and the workers connect to; DATABASEURL is used by the migrations.\n'
          '\n'
          'Let ScipionWeb do it:\n'
          './scripts/scipionapi multinode enable --network   changes these lines, makes PostgreSQL and Valkey listen '
          'on the network (Valkey with a password, PostgreSQL only for that network), and opens the firewall. Try it '
          'with --dry-run first. ➡️ multinode enable\n'
          '\n'
          'This is the single most common multi-node mistake:\n'
          'If these stay on localhost, worker nodes will start, look healthy in their own logs, and simply never '
          'receive any task — because they are talking to a broker on themselves, not the master.\n'
          '\n'
          '1.2 Export the shared filesystem\n'
          '\n'
          'Export scipionhome/projects (and ideally scipionhome/config) over NFS, or place them on whatever shared '
          'storage your infrastructure provides. Make sure the worker node IPs are allowed in the export.\n'
          '\n'
          '1.3 Validate before starting anything\n'
          '\n'
          'bash\n'
          'SCIPIONAPIDEPLOYMENTMODE=multi-node ./scripts/scipionapi doctor --strict\n'
          '\n'
          'With SCIPIONAPIDEPLOYMENTMODE=multi-node, doctor escalates three checks from warnings to hard failures: '
          'Broker reachability, Database reachability, and Projects filesystem (rejecting local-only filesystem '
          'types such as ext4 when it cannot confirm the path is shared). See doctor — Multi-Node Deployment Checks '
          'for what each check does.\n'
          '\n'
          'Fix everything doctor --strict reports before moving to the worker nodes.\n'
          '\n'
          "1.4 Start only the master's services\n"
          '\n'
          'bash\n'
          './scripts/scipionapi start --role api\n'
          './scripts/scipionapi start --role plugins\n'
          '\n'
          'Protocol execution is normally not run on the master, so the machine serving the web UI stays responsive. '
          'If the master also has spare capacity, --role protocols (or --role all) is a valid choice too. See start '
          '/ stop / restart / status / logs — --role.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-cluster/#step-1-master-setup'},
 {'area': 'installation',
  'page': 'Multi-Node Cluster Deployment',
  'title': 'Step 2 — Each Worker Node',
  'text': 'Repeat this for every worker node.\n'
          '\n'
          '2.1 Mount the shared filesystem\n'
          '\n'
          "Mount the master's NFS export at the exact same path used on the master (for example "
          'scipionhome/projects).\n'
          '\n'
          '2.2 Install ScipionAPI locally\n'
          '\n'
          'Install the same ScipionAPI version with its own Conda environment on this node (Manual Installation or '
          "Provision are the usual paths for a worker-only node — you do not need to run provision's admin-user "
          'bootstrap again if the database already exists).\n'
          '\n'
          '2.3 Install the plugins this node should run\n'
          '\n'
          'Install (via the plugin manager or scipionapicli) whatever plugins the protocols routed to this node '
          'actually need. GPU-heavy plugins typically only make sense on GPU-equipped nodes.\n'
          '\n'
          '2.4 Point .env at the master\n'
          '\n'
          'dotenv\n'
          'POSTGRESHOST=master.internal\n'
          'DATABASEURL=postgresql://scipionuser: @master.internal:5432/scipiondb\n'
          'BROKERURL=redis://: @master.internal:6379/0\n'
          '\n'
          "Copy these from the master's .env (with SECRETKEY and the database credentials): every node must use the "
          'same ones.\n'
          '\n'
          '2.5 Validate\n'
          '\n'
          'bash\n'
          'SCIPIONAPIDEPLOYMENTMODE=multi-node ./scripts/scipionapi doctor --strict\n'
          '\n'
          '2.6 Start only the protocol worker\n'
          '\n'
          'bash\n'
          './scripts/scipionapi start --role protocols\n'
          '\n'
          'For a node that should only receive a specific class of protocol (for example, a GPU node), give it its '
          'own Celery queue name instead of the shared default:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi start --role protocols --queue protocols-gpu\n'
          '\n'
          'Make the queue name persistent:\n'
          'A --queue passed on the command line only applies to that one start/restart invocation. To have the same '
          "queue name survive future restarts — including ones triggered from the web UI's worker restart button — "
          "set it in that node's .env instead:\n"
          '\n'
          'dotenv\n'
          'PROTOCOLSCELERYQUEUE=protocols-gpu',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-cluster/#step-2-each-worker-node'},
 {'area': 'installation',
  'page': 'Multi-Node Cluster Deployment',
  'title': 'Step 3 — Route Protocols to the Right Node',
  'text': 'By default every protocol dispatch goes to the shared protocols queue, and any protocol worker listening '
          'on it can pick it up — this is unchanged and safe even if you never touch queue routing.\n'
          '\n'
          'To send specific protocols to a specific node, reuse the Host name you already assign per protocol in '
          'Hosts and Queues (the same value used for SLURM partition selection). Create or edit:\n'
          '\n'
          'text\n'
          'scipionhome/config/celeryqueuerouting.json\n'
          '\n'
          'json\n'
          '{\n'
          '"gpu-cluster": "protocols-gpu"\n'
          '}\n'
          '\n'
          '"gpu-cluster" here is a Host name as configured in Settings > Host / hosts.conf, not a Celery worker '
          'name. Any protocol launched with that host now dispatches straight to the protocols-gpu queue — which '
          'only the node started with --queue protocols-gpu consumes. Hosts with no entry in this file keep going to '
          'the plain protocols queue, exactly like a single-node deployment.\n'
          '\n'
          'Because scipionhome/config is on the shared filesystem, this file only needs to exist once and every '
          'node/master sees the same mapping immediately.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-cluster/#step-3-route-protocols-to-the-right-node'},
 {'area': 'installation',
  'page': 'Multi-Node Cluster Deployment',
  'title': 'Step 4 — Verify the Cluster',
  'text': '4.1 Confirm every worker answers\n'
          '\n'
          'From the master (or any node with network access to Valkey):\n'
          '\n'
          'bash\n'
          'python -m celery -A app.workers.taskqueue inspect ping\n'
          '\n'
          'You should see one protocols@  entry per worker node, plus plugins@ .\n'
          '\n'
          '4.2 Check the dashboard\n'
          '\n'
          'Open Settings > Jobs in the web UI (admin only). Each worker shows up as its own card. Click Refresh '
          'nodes to broadcast a capability report to every node and confirm, per node, which GPUs and plugins are '
          'actually installed there — this is the fastest way to catch "I forgot to install this plugin on worker 2" '
          'before a protocol launch fails on it.\n'
          '\n'
          '4.3 Launch a test protocol on the routed queue\n'
          '\n'
          'Launch a protocol whose Host maps to protocols-gpu in celeryqueuerouting.json, and confirm in Settings > '
          "Jobs > Active jobs that its worker column shows the GPU node's hostname, not one of the plain protocols "
          'workers.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-cluster/#step-4-verify-the-cluster'},
 {'area': 'installation',
  'page': 'Multi-Node Cluster Deployment',
  'title': 'Networking Checklist',
  'text': "- [ ] DATABASEURL / BROKERURL on every worker point to the master's routable hostname/IP, not localhost\n"
          "- [ ] PostgreSQL (5432) and Valkey (6379) accept connections from every worker's IP (firewall / security "
          'group / pghba.conf)\n'
          "- [ ] The NFS (or equivalent) export allows every worker's IP\n"
          '- [ ] SCIPIONAPIDEPLOYMENTMODE=multi-node ./scripts/scipionapi doctor --strict passes on the master and '
          'on every worker\n'
          '- [ ] Each worker node has the plugins it needs installed locally\n'
          '- [ ] scipionhome/config/celeryqueuerouting.json (if used) is reachable from every node through the '
          'shared filesystem',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-cluster/#networking-checklist'},
 {'area': 'installation',
  'page': 'Multi-Node Cluster Deployment',
  'title': 'Common Issues',
  'text': "Worker looks 'ready' in its own log but never runs anything:\n"
          'Almost always DATABASEURL/BROKERURL still pointing at localhost on that node. Re-run doctor --strict with '
          'SCIPIONAPIDEPLOYMENTMODE=multi-node — this is exactly the case it is designed to catch.\n'
          '\n'
          'Protocol stays in Scheduled/Launched forever:\n'
          'Confirm the Celery broker queue actually has a consumer: python -m celery -A app.workers.taskqueue '
          'inspect activequeues. If a worker was started and then the broker connection was interrupted (network '
          'blip, VPN drop), the process can stay alive without actually consuming tasks. Restarting that one worker '
          '(./scripts/scipionapi runtime restart --role protocols) recovers it; this is an operational Celery/Redis '
          'quirk, not something specific to this deployment mode.\n'
          '\n'
          'A protocol fails immediately with an import/plugin error on one node but not another:\n'
          'The plugin it needs is not installed on the node that picked it up. Use Settings > Jobs > Refresh nodes '
          "to confirm per-node plugin inventory before assuming code is broken, and route that protocol's Host to a "
          'queue only consumed by nodes that have the plugin.\n'
          '\n'
          'celeryqueuerouting.json changes do not seem to take effect:\n'
          'The mapping is read fresh on every dispatch, so no restart is needed — but it is read from '
          'SCIPIONHOME/config/, so double-check the file actually landed on the shared mount and not on a single '
          "node's local disk.",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-cluster/#common-issues'},
 {'area': 'installation',
  'page': 'Multi-Node Cluster Deployment',
  'title': 'Navigation',
  'text': '← Previous: Production Deployment\n\nNext: doctor command →',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-cluster/#navigation'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'The machines',
  'text': '| Machine | IP | Hardware | Role |\n'
          '|---|---|---|---|\n'
          '| scipion-master | 10.0.0.10 | CPU only, no GPU | Web, database, job queue. Runs no protocols |\n'
          '| gpu-01 | 10.0.0.21 | 4 GPUs | Runs protocols |\n'
          '| gpu-02 | 10.0.0.22 | 4 GPUs | Runs protocols |\n'
          '\n'
          "The master needs no GPU: it runs no protocols, and the web's viewers only use the CPU.\n"
          '\n'
          'When it is finished:\n'
          '\n'
          'text\n'
          'users ──► scipion-master (web + database + queue)     ← no GPU, no protocols\n'
          '│\n'
          '"protocols" queue\n'
          '┌──────┴──────┐\n'
          '▼             ▼\n'
          'gpu-01        gpu-02          ← each takes a protocol when it has room',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#the-machines'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'Step 0 — Prepare the machines (once, usually by the system administrators)',
  'text': 'Three things must be ready before ScipionWeb.\n'
          '\n'
          'a) One shared disk\n'
          '\n'
          'The home of the user scipion must be the same on the three machines. That is where ScipionWeb, its Conda '
          'environment and the projects will live.\n'
          '\n'
          'If your machines already share their homes (NFS, LDAP…), skip this. Otherwise, the usual way is NFS from '
          'the master:\n'
          '\n'
          'bash\n'
          'on scipion-master\n'
          'sudo apt install nfs-kernel-server\n'
          'echo "/home/scipion 10.0.0.0/24(rw,sync,nosubtreecheck)" | sudo tee -a /etc/exports\n'
          'sudo exportfs -ra\n'
          '\n'
          'bash\n'
          'on gpu-01 and on gpu-02\n'
          'sudo apt install nfs-common\n'
          'sudo mount scipion-master:/home/scipion /home/scipion\n'
          'echo "scipion-master:/home/scipion /home/scipion nfs defaults 0 0" | sudo tee -a /etc/fstab\n'
          '\n'
          "The data too: the microscopes' folders and the data disks your users import must also be at the same path "
          'everywhere, for example /data/offload.\n'
          '\n'
          'b) The same user, with the same uid\n'
          '\n'
          'bash\n'
          'id -u scipion     # on the three machines: the same number\n'
          '\n'
          'If it differs, make it equal (sudo usermod -u   scipion) before going on.\n'
          '\n'
          'c) The GPU drivers on the GPU nodes\n'
          '\n'
          'bash\n'
          'nvidia-smi        # on gpu-01 and gpu-02: it lists the 4 GPUs\n'
          '\n'
          'Check before going on\n'
          '\n'
          'bash\n'
          'on gpu-01 (and gpu-02), as scipion\n'
          'ls ~                       # the same files as on the master\n'
          'touch ~/test-from-gpu-01   # then, on the master: ls ~/test-from-gpu-01',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#step-0-prepare-the-machines-once-usually-by-the-system-administrators'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'Step 1 — Install ScipionWeb on the master',
  'text': 'On scipion-master, as scipion. Install Conda in the home (~/miniconda3), so that it is on the shared disk '
          'too.\n'
          '\n'
          'bash\n'
          'wget https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/install.sh\n'
          'chmod +x install.sh\n'
          './install.sh --check-only\n'
          './install.sh\n'
          '\n'
          'This is the normal installation, in ~/scipionweb. When it ends, you already have a working web: open the '
          'address it prints and sign in as the administrator.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#step-1-install-scipionweb-on-the-master'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'Step 2 — Open the master to the nodes',
  'text': 'Still on scipion-master. First look at the plan:\n'
          '\n'
          'bash\n'
          '~/scipionweb/scripts/scipionapi multinode enable --network 10.0.0.0/24 --dry-run\n'
          '\n'
          'If it looks right, do it (it asks for sudo):\n'
          '\n'
          'bash\n'
          '~/scipionweb/scripts/scipionapi multinode enable --network 10.0.0.0/24\n'
          '\n'
          'What changed:\n'
          '\n'
          '- PostgreSQL and Valkey accept the machines of 10.0.0.x, and only them, and Valkey got a password.\n'
          '- The .env now names scipion-master instead of localhost.\n'
          '- Every file was backed up first in ~/scipionweb/scipionhome/multinode/.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#step-2-open-the-master-to-the-nodes'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'Step 3 — Join the GPU nodes',
  'text': 'On gpu-01, as scipion:\n'
          '\n'
          'bash\n'
          '~/scipionweb/install.sh --join ~/scipionweb\n'
          '\n'
          'text\n'
          'Checking this machine (gpu-01) as a compute node\n'
          'OK     Multi-node installation      yes\n'
          'OK     Not the main node            this machine is gpu-01, the main node is scipion-master\n'
          'OK     Installation folder          /home/scipion/scipionweb\n'
          'OK     SCIPIONHOME                 /home/scipion/scipionweb/scipionhome\n'
          'OK     Projects folder              /home/scipion/scipionweb/scipionhome/projects\n'
          'OK     Same user as the main node   uid 1001\n'
          'OK     Database (from this node)    scipion-master:5432\n'
          'OK     Valkey (from this node)      scipion-master:6379\n'
          'OK     GPUs                         4\n'
          '...\n'
          'The worker of gpu-01 answers: it takes protocols from now on.\n'
          '\n'
          'It found the 4 GPUs, so it runs up to 4 protocols at a time. Do the same on gpu-02.\n'
          '\n'
          'If a line says FAIL, it explains why and nothing is changed: fix it (usually step 0) and run the same '
          'command again.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#step-3-join-the-gpu-nodes'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'Step 4 — Keep the master from computing',
  'text': 'On scipion-master:\n'
          '\n'
          'bash\n'
          '~/scipionweb/scripts/scipionapi multinode compute off\n'
          '\n'
          'From now on every protocol runs on gpu-01 or gpu-02.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#step-4-keep-the-master-from-computing'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'Step 5 — Check that it works',
  'text': 'bash\n'
          '~/scipionweb/scripts/scipionapi node list\n'
          '\n'
          'text\n'
          'Main node: scipion-master (does not run protocols)\n'
          'gpu-01     queue protocols   concurrency 4   answering\n'
          'gpu-02     queue protocols   concurrency 4   answering\n'
          '\n'
          'Then, in the web:\n'
          '\n'
          '1. Create a project and launch a quick protocol (an import, for example).\n'
          '2. On gpu-01 and gpu-02, run ~/scipionweb/scripts/scipionapi logs: one of them shows it running.\n'
          '3. The protocol finishes in the web as usual.\n'
          '\n'
          "That's the whole cluster.",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#step-5-check-that-it-works'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'Daily life',
  'text': '| I want to… | Where | What |\n'
          '|---|---|---|\n'
          '| Launch protocols | the web | As always. A free node takes each one; when both are full (4 + 4), the '
          'next waits in the queue |\n'
          '| Add a third node | the new node | Mount the disk (step 0), then install.sh --join ~/scipionweb |\n'
          '| Remove a node | that node | ~/scipionweb/scripts/scipionapi node leave |\n'
          '| Restart a node after a reboot | that node | ~/scipionweb/scripts/scipionapi start |\n'
          '| Update ScipionWeb | the master | scipionapi update, then scipionapi restart on each node |\n'
          "| Install a plugin | the web | It reaches every node through the shared disk; restart the nodes' workers "
          '|',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#daily-life'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'The GPUs: the user chooses them',
  'text': "Without SLURM, nobody shares out a node's GPUs. A protocol uses the GPU IDs written in its form, on the "
          'node that takes it:\n'
          '\n'
          '- GPU 0 means the first GPU of that node.\n'
          '- gpu-01 runs up to 4 protocols at a time. If two of them ask for GPU 0, they share it and may run out of '
          'memory.\n'
          '- So, protocols that run at the same time should use different GPU IDs: one 0, another 1, and so on.\n'
          '\n'
          "If something fails, the protocol's log says why. For automatic GPU sharing, use SLURM (below).",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#the-gpus-the-user-chooses-them'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'Later: machines that are not all alike',
  'text': 'Say you add cpu-01, a machine without GPUs, for the CPU-only protocols. GPU protocols must then go only '
          'to gpu-01 and gpu-02:\n'
          '\n'
          'bash\n'
          'on gpu-01 and gpu-02: leave, then join with a GPU queue and a host\n'
          '~/scipionweb/scripts/scipionapi node leave\n'
          '~/scipionweb/install.sh --join ~/scipionweb --queue protocols-gpu --host gpu-nodes\n'
          '\n'
          'on cpu-01: the normal queue\n'
          '~/scipionweb/install.sh --join ~/scipionweb\n'
          '\n'
          'Users then choose the host gpu-nodes in the form of a GPU protocol. Everything else runs on cpu-01.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#later-machines-that-are-not-all-alike'},
 {'area': 'installation',
  'page': 'Example: A Three-Machine Cluster, Step by Step',
  'title': 'The same cluster with SLURM',
  'text': 'If gpu-01 and gpu-02 are SLURM nodes, the cluster is built differently. Steps 2 to 4 are not needed:\n'
          '\n'
          '1. Step 0 as above: shared disk, same user, drivers, plus SLURM working (sinfo, and sbatch from '
          'scipion-master).\n'
          '2. Step 1 as above: install on scipion-master.\n'
          '3. Create a host with a queue in Settings → Hosts and Queues (sbatch, squeue, scancel, a template with '
          '--gres=gpu:%(GPUCOUNT)s, your partitions). ➡️ Hosts and Queues\n'
          "4. Users pick that host in the protocol's form.\n"
          '\n'
          "SLURM then chooses the node and the GPUs, and a protocol can leave its GPU IDs at 0. Keep the master's "
          'protocol worker on (no compute off): it submits the jobs and follows them. ➡️ With SLURM',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node-example/#the-same-cluster-with-slurm'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Without SLURM: compute nodes',
  'text': 'You install ScipionWeb once, on the main node. Each compute node joins with one command, and new nodes '
          'can be added or removed at any time.\n'
          '\n'
          'text\n'
          '┌──────────── MAIN NODE ────────────┐\n'
          'browser ──────┤  web + API · PostgreSQL · Valkey  │\n'
          '│  (no protocols: step 4)           │\n'
          '└────────────────┬──────────────────┘\n'
          '│  job queue (Valkey)\n'
          '┌───────────────────┼───────────────────┐\n'
          '▼                   ▼                   ▼\n'
          '┌────────────┐      ┌────────────┐      ┌────────────┐\n'
          '│  node 1    │      │  node 2    │      │  GPU node  │\n'
          '│ "protocols"│      │ "protocols"│      │"protocols- │\n'
          '│   queue    │      │   queue    │      │    gpu"    │\n'
          '└────────────┘      └────────────┘      └────────────┘\n'
          'all of them see the same installation (shared disk)\n'
          '\n'
          'How it works:\n'
          '\n'
          '1. A user launches a protocol in the web.\n'
          '2. The API puts it in a queue.\n'
          '3. A free worker on any node takes it, runs it and writes its results to the shared disk and the main '
          "node's database.\n"
          '\n'
          'Nodes listening to the same queue share the work. A node with its own queue (for example, the GPU nodes) '
          'only takes the protocols sent to that queue.\n'
          '\n'
          "The GPUs are the user's choice:\n"
          "Without SLURM, nobody shares out a node's GPUs. A protocol uses the GPU IDs written in its form, on "
          'whichever node takes it.\n'
          '\n'
          '- Two protocols on the same node with the same GPU ID share that GPU, and can fail for lack of memory.\n'
          '- Users must choose different GPU IDs for protocols running at the same time.\n'
          '- Alternatively, give a node a --concurrency no higher than the protocols its GPUs can hold.\n'
          '\n'
          "If something fails, the protocol's log says so. For automatic GPU sharing, use SLURM.",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#without-slurm-compute-nodes'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Before you start: three requirements',
  'text': '1. One shared disk, at the same path everywhere:\n'
          'Every node must see, at exactly the same paths as the main node:\n'
          '\n'
          "- the installation folder (by default ~/scipionweb, with its scipionhome: settings, Scipion's software "
          'and plugins, projects, logs);\n'
          '- the Conda environment of ScipionWeb (by default under ~/miniconda3);\n'
          '- the data your users import (microscope folders, data disks…).\n'
          '\n'
          'The usual way is an NFS home (or an NFS disk mounted at the same path) on every machine. ScipionWeb '
          'stores absolute paths: a node that sees a folder under another path cannot use it.\n'
          '\n'
          '2. The same user, with the same uid:\n'
          'Run ScipionWeb on every node as the same Linux user, with the same uid. Check with id -u on each machine. '
          'Files written by a node must belong to the same owner as on the main node.\n'
          '\n'
          '3. The nodes reach the main node:\n'
          "- The nodes need the main node's network name, for example krios-server.cnb.csic.es.\n"
          '- They need ports 5432 (PostgreSQL) and 6379 (Valkey) open to them. The first step below configures '
          'both.\n'
          '\n'
          'Nothing else has to be installed on the nodes. Scipion, the plugins and their programs come from the '
          'shared disk, so a plugin installed from the web reaches every node.\n'
          '\n'
          'Nodes with their own local installation:\n'
          'If your nodes cannot share the installation and the Conda environment, follow Multi-Node: Manual Setup '
          'instead. Step 2 below (multinode enable) is useful there too.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#before-you-start-three-requirements'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Step 1 — Install the main node',
  'text': 'Install ScipionWeb normally on the machine that will run the web, in a folder on the shared disk (Guided '
          'Installation, or without Internet):\n'
          '\n'
          'bash\n'
          './install.sh',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#step-1-install-the-main-node'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Step 2 — Open the main node to the nodes',
  'text': "On the main node, tell ScipionWeb your nodes' network. Preview first: nothing changes with --dry-run.\n"
          '\n'
          'bash\n'
          '~/scipionweb/scripts/scipionapi multinode enable --network 10.0.0.0/24 --dry-run\n'
          '\n'
          'text\n'
          'Opening this main node (krios-server.cnb.csic.es) to the nodes of 10.0.0.0/24\n'
          '1. PostgreSQL: listen on the network and let scipionuser into scipiondb from 10.0.0.0/24 (pghba.conf), '
          'then restart it\n'
          '2. Valkey: listen on the network with a password (valkey.conf), then restart it. ...\n'
          '3. Firewall: if ufw is active, let 10.0.0.0/24 reach ports 5432 and 6379\n'
          '4. .env: name this machine as krios-server.cnb.csic.es instead of localhost, multi-node\n'
          '5. Restart the API and the workers of this machine with the new settings\n'
          'Dry run: nothing changed.\n'
          '\n'
          'If the plan looks right, run it (it asks for sudo once):\n'
          '\n'
          'bash\n'
          '~/scipionweb/scripts/scipionapi multinode enable --network 10.0.0.0/24\n'
          '\n'
          'What it changes:\n'
          '\n'
          '| Where | Change |\n'
          '|---|---|\n'
          "| PostgreSQL | Listens on the network, and lets in only ScipionWeb's own user and database, only from "
          'your network |\n'
          '| Valkey | Listens on the network and gets a password (a new one, or the one it already had) |\n'
          '| Firewall | If ufw is active, opens ports 5432 and 6379 to your network only |\n'
          "| .env | Uses the machine's network name instead of localhost, and marks the installation as multi-node "
          '|\n'
          '\n'
          'Everything is backed up first:\n'
          'Every file it changes (pghba.conf, valkey.conf, .env) is copied first to scipionhome/multinode/backup- /. '
          'To undo, copy them back and restart PostgreSQL, Valkey and ScipionWeb.\n'
          '\n'
          'Options:\n'
          '- --host NAME: the name the nodes use to reach this machine. The default is its full host name; give '
          'another if the nodes know it by a different name or IP.\n'
          '- --yes: no confirmation question, for scripts.\n'
          '\n'
          'Valkey gets a password:\n'
          'Any other program on the main node that uses Valkey without a password stops reaching it. ScipionWeb '
          'itself is updated automatically.\n'
          '\n'
          'At the end it checks that the database and Valkey answer on the network name, and prints the command for '
          'the nodes.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#step-2-open-the-main-node-to-the-nodes'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Step 3 — Join each compute node',
  'text': 'On each compute node, as the same user, run the installer with --join and the installation folder:\n'
          '\n'
          'bash\n'
          '~/scipionweb/install.sh --join ~/scipionweb\n'
          '\n'
          '(install.sh is the same file you installed with; any copy works. Inside the installation, the equivalent '
          'command is ~/scipionweb/scripts/scipionapi node join.)\n'
          '\n'
          'It checks the machine and starts its worker:\n'
          '\n'
          'text\n'
          'Checking this machine (node-01) as a compute node\n'
          'OK     Multi-node installation      yes\n'
          'OK     Not the main node            this machine is node-01, the main node is krios-server\n'
          'OK     Installation folder          /home/scipion/scipionweb\n'
          'OK     SCIPIONHOME                 /home/scipion/scipionweb/scipionhome\n'
          'OK     Projects folder              /home/scipion/scipionweb/scipionhome/projects\n'
          'OK     Same user as the main node   uid 1001\n'
          'OK     Database (from this node)    krios-server.cnb.csic.es:5432\n'
          'OK     Valkey (from this node)      krios-server.cnb.csic.es:6379\n'
          'OK     GPUs                         2\n'
          '...\n'
          'The worker of node-01 answers: it takes protocols from now on.\n'
          '\n'
          'If a check fails, it says why and changes nothing. Fix it and run the same command again.\n'
          '\n'
          "That's it: the node takes protocols from the protocols queue together with the main node.\n"
          '\n'
          '| Option | What it does | Default |\n'
          '|---|---|---|\n'
          '| --queue NAME | The queue the node takes protocols from | protocols |\n'
          '| --concurrency N | How many protocols it runs at a time | its number of GPUs, or 4 |\n'
          "| --host NAME | Sends the protocols of this Scipion host to the node's queue (see below) | — |",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#step-3-join-each-compute-node'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Step 4 — Keep the main node from computing',
  'text': 'Until now the main node runs protocols too, which is handy while you add the nodes. Once they work, leave '
          'all the computing to them, so the web, the database and the viewers always respond fast. On the main '
          'node:\n'
          '\n'
          'bash\n'
          '~/scipionweb/scripts/scipionapi multinode compute off\n'
          '\n'
          'What it does:\n'
          '\n'
          "- It stops the main node's protocol worker.\n"
          '- It writes SCIPIONAPIMAINRUNSPROTOCOLS=0 to the .env, so the worker does not start again with start, '
          "restart or update, and the web's worker buttons do not start it either.\n"
          '- From then on, every protocol waits in the queue for a compute node.\n'
          '\n'
          'Protocols running on the main node:\n'
          'If protocols are running on the main node, it refuses: stopping its worker would kill them. Wait until '
          'they finish, or add --force.\n'
          '\n'
          'No node answering?:\n'
          'It tells you when no compute node answers. Protocols launched meanwhile are not lost: they wait in the '
          'queue until a node joins or starts.\n'
          '\n'
          'Not with SLURM:\n'
          "Protocols sent to SLURM are submitted (sbatch) and followed by the main node's protocol worker, which "
          "only submits and waits. With compute off nobody submits them. If you use SLURM, leave the main node's "
          'worker on.\n'
          '\n'
          'To let the main node compute again: scipionapi multinode compute on.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#step-4-keep-the-main-node-from-computing'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Send some protocols to some nodes (GPU nodes)',
  'text': 'By default every node shares one queue: any protocol can run on any node. To send, for example, GPU '
          'protocols to the GPU nodes only, give those nodes their own queue and a host name:\n'
          '\n'
          'bash\n'
          'on each GPU node\n'
          '~/scipionweb/install.sh --join ~/scipionweb --queue protocols-gpu --host gpu-nodes\n'
          '\n'
          'This:\n'
          '\n'
          "1. starts the node's worker on the protocols-gpu queue;\n"
          '2. creates the Scipion host gpu-nodes (a copy of localhost), if it does not exist;\n'
          '3. sends every protocol run on host gpu-nodes to the protocols-gpu queue.\n'
          '\n'
          "Users then choose gpu-nodes as the host in the protocol's form (its execution settings), and the protocol "
          'runs on a GPU node. Protocols on localhost keep running on the other nodes.\n'
          '\n'
          'Several groups of nodes:\n'
          'Repeat with other names: --queue protocols-bigmem --host bigmem-nodes, and so on. The mapping is kept in '
          "scipionhome/config/celeryqueuerouting.json. Edit a host's settings in Settings → Hosts and Queues.",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#send-some-protocols-to-some-nodes-gpu-nodes'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'With SLURM',
  'text': 'When the cluster has SLURM, ScipionWeb does not need compute nodes of its own:\n'
          '\n'
          'text\n'
          'browser ──► main node (web, database, protocol worker)\n'
          '│   the worker only submits and waits\n'
          '▼   sbatch\n'
          'SLURM ──► node-01 · node-02 · gpu-01 …   (SLURM chooses node, GPUs, memory, time)\n'
          '\n'
          '1. Install ScipionWeb on a machine that can submit to SLURM, the one where sbatch and squeue work, in a '
          'folder on the shared disk (Guided Installation).\n'
          '2. Check that the SLURM nodes see the same paths: the installation, the Conda environment and the data. A '
          'SLURM job runs Scipion from there.\n'
          '3. Create a host with a queue in Settings → Hosts and Queues: the submit, check and cancel commands, a '
          'submit template asking for --gres=gpu:%(GPUCOUNT)s, and your partitions. Step by step: Hosts and Queues.\n'
          "4. Users choose that host in the protocol's form, with its partition, time, memory and number of GPUs.\n"
          '\n'
          'The GPUs.\n'
          '\n'
          '- SLURM gives each job its own GPUs, and the job only sees those (with gres and cgroups configured).\n'
          "- A protocol asking for GPU 0 uses the first GPU of its job, never another job's.\n"
          '- So, with SLURM, users can leave the GPU IDs at 0 (or 0 1 for two).\n'
          '\n'
          "Keep the main node's protocol worker on:\n"
          'It runs no science: it submits the job and follows it until it ends. Do not use multinode compute off '
          'here.\n'
          '\n'
          'Mixing both ways:\n'
          'A cluster with SLURM can also have compute nodes joined to ScipionWeb, for example a GPU workstation '
          "outside SLURM. Protocols on the SLURM host go to SLURM; protocols on the node's host go to the node (Send "
          'some protocols to some nodes).',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#with-slurm'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Check the installation',
  'text': 'From any node:\n'
          '\n'
          'bash\n'
          '~/scipionweb/scripts/scipionapi node list\n'
          '\n'
          'text\n'
          'Main node: krios-server\n'
          'node-01              queue protocols          concurrency 4   answering\n'
          'gpu-01               queue protocols-gpu      concurrency 2   answering\n'
          'protocols@krios-server   protocols\n'
          'plugins@krios-server     plugins\n'
          '\n'
          'On a node, scipionapi status shows its worker, and scipionapi doctor checks it (database, Valkey, shared '
          'folders…).',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#check-the-installation'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Everyday operations',
  'text': '| Task | Where | Command |\n'
          '|---|---|---|\n'
          "| Restart a node's worker | the node | scipionapi restart |\n"
          '| Stop a node | the node | scipionapi stop |\n'
          '| Start it again (after a reboot) | the node | scipionapi start |\n'
          "| See a node's logs | the node | scipionapi logs (they are in scipionhome/logs/nodes/ /) |\n"
          '| Remove a node | the node | scipionapi node leave |\n'
          '| Update ScipionWeb | the main node | scipionapi update, then scipionapi restart on each node |\n'
          "| Install a plugin | the web | it reaches every node through the shared disk; restart the nodes' workers "
          '|\n'
          '\n'
          'On a compute node, start, stop, restart and status act on its protocol worker only: the API never starts '
          'there.\n'
          '\n'
          "Start the node's worker at boot:\n"
          'Put scipionapi start in a @reboot crontab entry of the ScipionWeb user, or in a systemd unit. See '
          'Production Deployment.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#everyday-operations'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'Troubleshooting',
  'text': '| What you see | Why | Fix |\n'
          '|---|---|---|\n'
          '| Multi-node installation: not yet | Step 2 was not run | Run multinode enable on the main node |\n'
          '| Installation folder: not found here | The shared disk is not mounted, or under another path | Mount it '
          'at the same path as on the main node |\n'
          '| Same user as the main node fails | Another user, or another uid | Use the same user; make its uid the '
          'same on every machine (LDAP, or usermod -u) |\n'
          '| Database (from this node) fails | Firewall, wrong network in step 2, or the node uses another name for '
          'the main node | Check --network; try nc -zv   5432; run multinode enable --host   |\n'
          '| Valkey (from this node) fails | Same as above, port 6379 | Same as above |\n'
          '| The node answers, but protocols never run there | They go to another queue | Check node list, the host '
          "chosen in the protocol's form, and celeryqueuerouting.json |\n"
          '| A protocol fails only on one node | A program or a data folder missing on that node | Check that the '
          "node sees the same data paths; see the node's celery-protocols.log |",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#troubleshooting'},
 {'area': 'installation',
  'page': 'Several Machines (Multi-Node)',
  'title': 'What runs where',
  'text': '| Part | Main node | Compute node |\n'
          '|---|---|---|\n'
          '| Web and API | ✅ | — |\n'
          '| PostgreSQL, Valkey | ✅ | — |\n'
          '| Plugin installation worker | ✅ | — |\n'
          '| Protocols | only until multinode compute off | ✅ |\n'
          '| Viewers, wizards, summaries | ✅ (they need the plugins and the data too) | — |\n'
          "| Facility session watcher | ✅ (it needs the microscopes' folders) | — |\n"
          '\n'
          'Security:\n'
          'Opening the database and Valkey to a network is safe only on a trusted internal network. Keep the network '
          'in step 2 as small as possible. ➡️ Security Notes',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/multi-node/#what-runs-where'},
 {'area': 'installation',
  'page': 'Installing Without Internet',
  'title': '1. Get the release files',
  'text': 'On a machine with Internet, download the four files of a release from the release server:\n'
          '\n'
          '| File | What it is |\n'
          '|---|---|\n'
          '| install.sh | The installer |\n'
          '| ScipionAPI- .zip | The server (API) |\n'
          '| ScipionWeb- -dist.zip | The web interface |\n'
          '| manifest.json | Optional: the list of releases with their checksums. With it, the installer verifies '
          'the files |\n'
          '\n'
          'For example, for v4.0.0:\n'
          '\n'
          'bash\n'
          'BASE=https://scipion.cnb.csic.es/downloads/scipion/scipionWeb\n'
          'mkdir scipionweb-v4.0.0 && cd scipionweb-v4.0.0\n'
          'wget $BASE/install.sh $BASE/ScipionAPI-v4.0.0.zip $BASE/ScipionWeb-v4.0.0-dist.zip $BASE/manifest.json\n'
          'chmod +x install.sh\n'
          '\n'
          'Copy the folder to the target machine: a USB stick, scp, a shared folder…',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/offline-install/#1-get-the-release-files'},
 {'area': 'installation',
  'page': 'Installing Without Internet',
  'title': '2. Install',
  'text': 'Run the installer from that folder:\n'
          '\n'
          'bash\n'
          'cd scipionweb-v4.0.0\n'
          './install.sh\n'
          '\n'
          'It says so when it uses the local files:\n'
          '\n'
          'text\n'
          '[OK]     Using the local release archives in /media/usb/scipionweb-v4.0.0: nothing is downloaded\n'
          '\n'
          'If the files are somewhere else, point to them:\n'
          '\n'
          'bash\n'
          './install.sh --local-dir /media/usb/scipionweb-v4.0.0\n'
          '\n'
          'Every other option works as in the Guided Installation: --install-dir, --user, --email, '
          '--non-interactive…\n'
          '\n'
          'Which version does it install?:\n'
          '- With manifest.json: the release that the manifest calls latest, or the one you ask for with --version.\n'
          '- Without it: the version in the file names (the newest one, if there are several).\n'
          '\n'
          'If you copied an older release together with a newer manifest.json, ask for it by name: ./install.sh '
          "--version v4.0.0. Otherwise the installer looks for the manifest's latest files and, as they are not in "
          'the folder, tries to download them.\n'
          '\n'
          'Both ZIP files are needed:\n'
          'The API and Web files of the same version must both be in the folder. If one is missing, the installer '
          'tries to download it.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/offline-install/#2-install'},
 {'area': 'installation',
  'page': 'Installing Without Internet',
  'title': '3. Update later, also without Internet',
  'text': 'Put the files of the new release (both ZIP files and manifest.json) in a folder, and give it to the '
          'updater as a file:// address:\n'
          '\n'
          'bash\n'
          '~/scipionweb/scripts/scipionapi update --base-url file:///media/usb/scipionweb-v4.1.0/\n'
          '\n'
          'Preview first with --dry-run. ➡️ Upgrade Guide',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/offline-install/#3-update-later-also-without-internet'},
 {'area': 'installation',
  'page': 'Installing Without Internet',
  'title': 'Several machines without Internet',
  'text': "Install the main node as above. Compute nodes download nothing: they use the main node's installation on "
          'the shared disk. ➡️ Several Machines (Multi-Node)',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/offline-install/#several-machines-without-internet'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': 'What you need',
  'text': 'A normal ScipionWeb deployment requires:\n'
          '\n'
          '- Linux\n'
          '- Conda (Miniconda or Anaconda)\n'
          '- PostgreSQL\n'
          '- Valkey\n'
          '- sudo privileges for the common local PostgreSQL bootstrap path\n'
          '- curl or wget\n'
          '- unzip\n'
          '- enough disk space for the downloaded bundles, Conda environment, projects, logs, and updates\n'
          '\n'
          'The installation flow uses these pieces to:\n'
          '\n'
          '- create or reuse the Python environment\n'
          '- configure the PostgreSQL database and role\n'
          '- run migrations\n'
          '- deploy the compiled Web UI\n'
          '- run FastAPI and Celery services',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#what-you-need'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': 'Supported operating system',
  'text': 'Recommended\n'
          '\n'
          '- Ubuntu 22.04 / 24.04\n'
          '- Debian 12+\n'
          '\n'
          'Other Linux distributions:\n'
          'Other Linux distributions may work, but package names and service-management commands can differ.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#supported-operating-system'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': '1. Install Conda',
  'text': 'ScipionAPI uses Conda to manage its Python environment.\n'
          '\n'
          'Check whether Conda is already installed\n'
          '\n'
          'bash\n'
          'conda --version\n'
          '\n'
          'If that prints a version number, continue to PostgreSQL.\n'
          '\n'
          'Install Miniconda\n'
          '\n'
          'bash\n'
          'mkdir -p ~/Downloads\n'
          'cd ~/Downloads\n'
          'wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x8664.sh\n'
          'bash Miniconda3-latest-Linux-x8664.sh\n'
          '\n'
          'Follow the installer prompts, then restart your terminal or run:\n'
          '\n'
          'bash\n'
          'conda init bash\n'
          'exec bash\n'
          '\n'
          'Verify again:\n'
          '\n'
          'bash\n'
          'conda --version\n'
          '\n'
          'If conda is not on PATH\n'
          '\n'
          'For a standard Miniconda location:\n'
          '\n'
          'bash\n'
          'export PATH="$HOME/miniconda3/bin:$PATH"\n'
          'conda --version\n'
          '\n'
          'For Anaconda, adjust the path accordingly.\n'
          '\n'
          'The guided installer also accepts an explicit Conda executable:\n'
          '\n'
          'bash\n'
          'export SCIPIONAPICONDAEXE=/absolute/path/to/conda\n'
          '\n'
          'Make PATH changes persistent:\n'
          'If conda only works after a manual PATH change, make that shell configuration persistent before '
          'continuing.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#1-install-conda'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': '2. Install PostgreSQL',
  'text': 'PostgreSQL stores the ScipionWeb/ScipionAPI persistent application state.\n'
          '\n'
          'Install it on Ubuntu/Debian:\n'
          '\n'
          'bash\n'
          'sudo apt update\n'
          'sudo apt install -y postgresql postgresql-contrib\n'
          '\n'
          'Enable and start it:\n'
          '\n'
          'bash\n'
          'sudo systemctl enable --now postgresql\n'
          '\n'
          'Verify it:\n'
          '\n'
          'bash\n'
          'sudo systemctl status postgresql\n'
          'sudo -u postgres psql -d postgres -c "SELECT 1;"\n'
          '\n'
          'Why sudo access matters\n'
          '\n'
          'The standard local installation can create the PostgreSQL role and database through commands such as:\n'
          '\n'
          'bash\n'
          'sudo -u postgres psql ...\n'
          '\n'
          'The guided preflight validates this administrative path before installation.\n'
          '\n'
          'If your deployment uses a custom or remote PostgreSQL setup, use the manual installation documentation '
          'instead of relying on the default local bootstrap.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#2-install-postgresql'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': '3. Install Valkey',
  'text': 'Valkey is used as the Celery broker and result backend.\n'
          '\n'
          'Install it:\n'
          '\n'
          'bash\n'
          'sudo apt update\n'
          'sudo apt install -y valkey-server valkey-tools\n'
          '\n'
          'Enable and start it:\n'
          '\n'
          'bash\n'
          'sudo systemctl enable --now valkey-server\n'
          '\n'
          'Verify it:\n'
          '\n'
          'bash\n'
          'valkey-cli ping\n'
          '\n'
          'Expected output:\n'
          '\n'
          'text\n'
          'PONG',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#3-install-valkey'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': '4. Install the basic utilities',
  'text': 'The guided installer needs a download tool and ZIP extraction support.\n'
          '\n'
          'A practical Ubuntu/Debian package set is:\n'
          '\n'
          'bash\n'
          'sudo apt update\n'
          'sudo apt install -y \\\n'
          'curl \\\n'
          'wget \\\n'
          'unzip \\\n'
          'ca-certificates\n'
          '\n'
          'Only one of curl or wget is required by the installer, but having both available is useful for '
          'administration and troubleshooting.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#4-install-the-basic-utilities'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': '5. Ports',
  'text': 'PostgreSQL and Valkey normally use:\n'
          '\n'
          'text\n'
          'PostgreSQL: 5432\n'
          'Valkey:     6379\n'
          '\n'
          "ScipionWeb's API/Web port should not be assumed to be 8080.\n"
          '\n'
          'If no fixed port is requested, provisioning preserves an existing APIPORT where appropriate or selects a '
          'free port automatically and persists it in SCIPIONHOME/.env.\n'
          '\n'
          'To inspect the standard service ports:\n'
          '\n'
          'bash\n'
          "ss -ltnp | grep -E ':(5432|6379)\\b'\n"
          '\n'
          'If you plan to force a particular API/Web port, check that port explicitly before installation:\n'
          '\n'
          'bash\n'
          "ss -ltnp | grep ':39080\\b' || true\n"
          '\n'
          'Then pass it to the installer:\n'
          '\n'
          'bash\n'
          './install.sh --api-port 39080',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#5-ports'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': '6. Permissions and installation directory',
  'text': 'The installation user needs write access to the selected installation directory.\n'
          '\n'
          'The guided installer defaults to:\n'
          '\n'
          'text\n'
          '$HOME/scipionweb\n'
          '\n'
          'It deliberately rejects unsafe or ambiguous targets, including unrelated non-empty directories and an '
          'already-installed ScipionWeb tree.\n'
          '\n'
          'Avoid mixed ownership:\n'
          'Do not create parts of the ScipionWeb installation as root and then run the application as a regular user '
          'unless you intentionally manage ownership and permissions.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#6-permissions-and-installation-directory'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': '7. Run the official preflight',
  'text': 'Once the basic packages are installed, download the public installer:\n'
          '\n'
          'bash\n'
          'wget https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/install.sh\n'
          'chmod +x install.sh\n'
          '\n'
          'Then run:\n'
          '\n'
          'bash\n'
          './install.sh --check-only\n'
          '\n'
          'The check reports all detected missing software/configuration problems together. It validates, among '
          'other things:\n'
          '\n'
          '- Linux runtime\n'
          '- curl or wget\n'
          '- unzip\n'
          '- sudo\n'
          '- Conda\n'
          '- Conda base Python\n'
          '- PostgreSQL client\n'
          '- Valkey client\n'
          '- Valkey server response\n'
          '- PostgreSQL administrative access\n'
          '\n'
          'If everything is ready, the installer exits successfully without installing ScipionWeb.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#7-run-the-official-preflight'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': 'Fast sanity check',
  'text': 'These commands should all work before a normal installation:\n'
          '\n'
          'bash\n'
          'conda --version\n'
          'sudo systemctl is-active postgresql\n'
          'sudo systemctl is-active valkey-server\n'
          'valkey-cli ping\n'
          'sudo -u postgres psql -d postgres -c "SELECT 1;"\n'
          '\n'
          'Then confirm with the installer itself:\n'
          '\n'
          'bash\n'
          './install.sh --check-only',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#fast-sanity-check'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': 'Common prerequisite failures',
  'text': 'Conda not found\n'
          '\n'
          'Try the actual Conda path or set SCIPIONAPICONDAEXE:\n'
          '\n'
          'bash\n'
          'export SCIPIONAPICONDAEXE="$HOME/miniconda3/bin/conda"\n'
          './install.sh --check-only\n'
          '\n'
          'PostgreSQL is not running\n'
          '\n'
          'bash\n'
          'sudo systemctl status postgresql\n'
          'journalctl -u postgresql --no-pager -n 100\n'
          '\n'
          'Valkey is not responding\n'
          '\n'
          'bash\n'
          'sudo systemctl status valkey-server\n'
          'journalctl -u valkey-server --no-pager -n 100\n'
          '\n'
          'PostgreSQL administrative access fails\n'
          '\n'
          'Refresh sudo authentication:\n'
          '\n'
          'bash\n'
          'sudo -v\n'
          'sudo -u postgres psql -d postgres -c "SELECT 1;"\n'
          '\n'
          'If your host intentionally does not allow this local administrative path, use the advanced/manual '
          'database setup instead.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#common-prerequisite-failures'},
 {'area': 'installation',
  'page': 'Prerequisites',
  'title': 'Next step',
  'text': 'When ./install.sh --check-only succeeds, continue with the Guided Installation.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/prerequisites/#next-step'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'What `provision` can do',
  'text': 'It can:\n'
          '\n'
          '- bootstrap the Conda environment\n'
          '- install Python dependencies\n'
          '- install Scipion core packages when needed\n'
          '- create or update SCIPIONHOME\n'
          '- create or update .env\n'
          '- select or preserve the API/Web port\n'
          '- create PostgreSQL role and database in common local setups\n'
          '- run Alembic migrations\n'
          '- create or update the admin user\n'
          '- deploy and serve the Web bundle\n'
          '- start the API and Celery worker',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#what-provision-can-do'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'Integrated mode: API + Web',
  'text': 'For a manually downloaded release pair, run from the extracted ScipionAPI directory and pass the compiled '
          'Web ZIP:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.com" \\\n'
          '--web-dist "/path/to/ScipionWeb-v4.0.1-dist.zip"\n'
          '\n'
          'The CLI asks for the administrator password using a hidden prompt.\n'
          '\n'
          'For automation, use an environment variable:\n'
          '\n'
          'bash\n'
          "export SCIPIONAPIADMINPASSWORD=' '\n"
          '\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.com" \\\n'
          '--password-env SCIPIONAPIADMINPASSWORD \\\n'
          '--web-dist "/path/to/ScipionWeb-v4.0.1-dist.zip"\n'
          '\n'
          'Password options:\n'
          '--pass and --password remain available for compatibility, but a hidden prompt or --password-env is '
          'preferred because shell arguments can be stored in history or exposed through process inspection.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#integrated-mode-api-web'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'Integrated-mode result',
  'text': 'With a valid Web bundle, ScipionAPI configures an integrated deployment where:\n'
          '\n'
          '- the Web UI is served from /\n'
          '- the API is mounted under /api by default\n'
          '- API documentation is exposed under the API mount path, typically /api/docs\n'
          '- the Web build receives runtime API configuration rather than requiring a rebuild for each host\n'
          '\n'
          'The deployed Web content is stored under the configured SCIPIONHOME runtime tree.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#integrated-mode-result'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'API-only mode',
  'text': 'API-only mode is useful for developers or deployments where the frontend is hosted elsewhere:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.com"\n'
          '\n'
          'In API-only mode, no compiled Web distribution is deployed by this command.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#api-only-mode'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'Port behavior',
  'text': 'The API/Web port is not assumed to be a fixed 8080.\n'
          '\n'
          'When --api-port is omitted:\n'
          '\n'
          '1. an existing configured APIPORT is preserved when appropriate\n'
          '2. otherwise a free port is selected automatically\n'
          '3. the resolved value is persisted in SCIPIONHOME/.env\n'
          '\n'
          'To force a specific port:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.com" \\\n'
          '--web-dist "/path/to/ScipionWeb-v4.0.1-dist.zip" \\\n'
          '--api-port 39080\n'
          '\n'
          'After provisioning, inspect the selected value:\n'
          '\n'
          'bash\n'
          "grep '^APIPORT=' scipionhome/.env",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#port-behavior'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'Useful advanced options',
  'text': 'Examples of supported controls include:\n'
          '\n'
          'text\n'
          '--web-dist PATH\n'
          '--api-mount-path /api\n'
          '--api-base-url URL\n'
          '--api-port PORT\n'
          '--bootstrap / --no-bootstrap\n'
          '--env-name NAME\n'
          '--python VERSION\n'
          '--install-scipion-core / --no-install-scipion-core\n'
          '--scipion-core-packages "..."\n'
          '\n'
          'Use these options only when you have a deployment reason to override the defaults used by the guided '
          'installer.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#useful-advanced-options'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'When to call `provision` directly',
  'text': 'Direct provision is appropriate when:\n'
          '\n'
          '- you downloaded or built the API/Web ZIPs yourself\n'
          '- you are validating release artifacts\n'
          '- you need API-only mode\n'
          '- the frontend is hosted separately\n'
          '- you are building custom deployment automation\n'
          '- you need to customize the API mount path or runtime environment\n'
          '- you are debugging a specific installation layer\n'
          '\n'
          'For normal first-time installation, use Guided Installation.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#when-to-call-provision-directly'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'What happens during provisioning',
  'text': 'A typical integrated-mode run performs:\n'
          '\n'
          '1. Conda environment bootstrap when enabled\n'
          '2. Python dependency installation\n'
          '3. Scipion core installation when required\n'
          '4. SCIPIONHOME and runtime-directory creation\n'
          '5. .env generation/update\n'
          '6. API/Web port resolution\n'
          '7. PostgreSQL database/role preparation\n'
          '8. Alembic migrations\n'
          '9. admin-user creation/update\n'
          '10. Web bundle deployment\n'
          '11. API and Celery startup',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#what-happens-during-provisioning'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'Verify after provisioning',
  'text': 'Start with:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi status\n'
          './scripts/scipionapi doctor --quick\n'
          '\n'
          'Read the persisted port:\n'
          '\n'
          'bash\n'
          'APIPORT="$(grep \'^APIPORT=\' scipionhome/.env | tail -n 1 | cut -d= -f2-)"\n'
          'echo "$APIPORT"\n'
          '\n'
          'Then test the API using that actual value:\n'
          '\n'
          'bash\n'
          'curl "http://localhost:${APIPORT}/health"\n'
          '\n'
          'For integrated mode, open:\n'
          '\n'
          'text\n'
          'http://localhost: /\n'
          'http://localhost: /api/docs\n'
          '\n'
          'For deeper diagnostics:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi doctor\n'
          './scripts/scipionapi logs',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#verify-after-provisioning'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'Re-running `provision`',
  'text': 'provision is designed to be reusable in common installation and recovery scenarios:\n'
          '\n'
          '- the Conda environment is reused when already present\n'
          '- existing database state is not blindly dropped\n'
          '- admin credentials can be updated\n'
          '- the Web bundle can be redeployed\n'
          '- the configured API port is preserved unless intentionally changed\n'
          '\n'
          'For an already-installed packaged release that simply needs a newer version, prefer ./scripts/scipionapi '
          'update rather than treating the upgrade as a new provision.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#re-running-provision'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'Common issues',
  'text': 'Conda not found:\n'
          'Confirm the Conda executable or set SCIPIONAPICONDAEXE before provisioning.\n'
          '\n'
          'PostgreSQL administrative access failed:\n'
          'The standard local bootstrap expects working PostgreSQL plus sufficient privileges. Use the manual '
          'database path for custom/remote setups.\n'
          '\n'
          'Valkey not responding:\n'
          'Verify valkey-cli ping returns PONG.\n'
          '\n'
          'Web UI does not load:\n'
          'Confirm --web-dist points to the intended ScipionWeb release ZIP and inspect status, doctor, and logs.\n'
          '\n'
          'Assuming port 8080:\n'
          'Read APIPORT from .env or the provisioning output. Automatic port selection is supported and should be '
          'expected.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#common-issues'},
 {'area': 'installation',
  'page': 'Provision (One-Shot Runtime Setup)',
  'title': 'Relationship to the guided installer',
  'text': 'The public installation path is intentionally layered:\n'
          '\n'
          '> install.sh handles host checks + release resolution + downloads + checksum verification → provision '
          'handles runtime setup\n'
          '\n'
          'That separation keeps the end-user experience simple while preserving a powerful direct CLI for advanced '
          'deployments.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/provision/#relationship-to-the-guided-installer'},
 {'area': 'installation',
  'page': 'Optional: Desktop Viewers in the Browser',
  'title': 'How it behaves',
  'text': '| Where the browser is | What happens when a viewer is opened |\n'
          '|---|---|\n'
          '| On another computer | The viewer runs on the server and appears in a floating window inside ScipionWeb '
          '|\n'
          '| On the server itself, in front of its screen | The viewer opens on that screen, as before |\n'
          "| Any, but Xpra is not installed | The viewer opens on the server's screen, as before |\n"
          '\n'
          '- Closing the floating window closes the program on the server, and closing the program closes the '
          'window.\n'
          '- After reloading the page, the viewers that were open come back.\n'
          '- Each user can have 3 viewers open at the same time.\n'
          '- A viewer that nobody uses for 15 minutes is closed.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/remote-viewers/#how-it-behaves'},
 {'area': 'installation',
  'page': 'Optional: Desktop Viewers in the Browser',
  'title': '1. Install Xpra (Ubuntu)',
  'text': 'This needs administrator rights (sudo). It adds the official Xpra repository and installs Xpra and its '
          'web page:\n'
          '\n'
          'bash\n'
          'Ubuntu version name: jammy (22.04), noble (24.04)…\n'
          'CODENAME=$(lsbrelease -cs); echo $CODENAME\n'
          '\n'
          'sudo wget -O /usr/share/keyrings/xpra.asc https://xpra.org/xpra.asc\n'
          'sudo wget -O /etc/apt/sources.list.d/xpra.sources \\\n'
          'https://raw.githubusercontent.com/Xpra-org/xpra/master/packaging/repos/$CODENAME/xpra.sources\n'
          '\n'
          'sudo apt update\n'
          'sudo apt install -y xpra xpra-html5\n'
          '\n'
          'Check it:\n'
          '\n'
          'bash\n'
          'xpra --version\n'
          '\n'
          'For other systems (Rocky, AlmaLinux, Fedora, Debian…), follow the instructions on the Xpra download page. '
          'Install both xpra and xpra-html5.\n'
          '\n'
          'Use the official repository:\n'
          'The xpra package of the distribution itself is often old and may come without the web page (xpra-html5). '
          'Install it from the Xpra repository as shown above.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/remote-viewers/#1-install-xpra-ubuntu'},
 {'area': 'installation',
  'page': 'Optional: Desktop Viewers in the Browser',
  'title': '2. Restart ScipionWeb',
  'text': 'bash\nscipionapi restart\n\nThen reload ScipionWeb in the browser. Nothing else needs configuring.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/remote-viewers/#2-restart-scipionweb'},
 {'area': 'installation',
  'page': 'Optional: Desktop Viewers in the Browser',
  'title': '3. Check it works',
  'text': 'From another computer:\n'
          '\n'
          '1. Open a project and select a protocol with a volume output.\n'
          '2. Open the output with its desktop viewer.\n'
          '3. A floating window should appear with "Opening the viewer on the server…", and then the program.\n'
          '\n'
          "If no floating window appears (the viewer opens on the server's own screen, or fails to open), ScipionWeb "
          'did not find Xpra: check xpra --version as the user that runs ScipionWeb and restart it again.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/remote-viewers/#3-check-it-works'},
 {'area': 'installation',
  'page': 'Optional: Desktop Viewers in the Browser',
  'title': 'Network and security',
  'text': '- No new ports. Everything goes through the same address and port as ScipionWeb. Xpra only listens inside '
          'the server.\n'
          '- Each viewer has its own random key and password. A user only sees and closes their own viewers.\n'
          "- File transfer, printing, sound, webcam and starting other programs from the viewer's page are turned "
          'off.\n'
          '- Behind a reverse proxy (nginx, Apache), the proxy must pass WebSocket connections to ScipionWeb under '
          '/api/.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/remote-viewers/#network-and-security'},
 {'area': 'installation',
  'page': 'Optional: Desktop Viewers in the Browser',
  'title': 'Several machines',
  'text': 'The viewers run on the machine that runs the ScipionWeb server (the main node). Install Xpra there. The '
          'data must be readable from that machine at the same paths, as is already required for multi-node setups.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/remote-viewers/#several-machines'},
 {'area': 'installation',
  'page': 'Optional: Desktop Viewers in the Browser',
  'title': 'If 3D is slow',
  'text': "By default the picture is drawn by the server's processor. This is fine for most maps, but large maps or "
          'complex scenes may feel slow. If the server has a GPU, VirtualGL lets the viewers use it. It is not '
          'needed to start.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/remote-viewers/#if-3d-is-slow'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Upgrade mental model',
  'text': 'A safe upgrade preserves three things correctly:\n'
          '\n'
          '1. the runtime workspace (SCIPIONHOME)\n'
          '2. the database state\n'
          '3. the version alignment between ScipionAPI and ScipionWeb\n'
          '\n'
          'The updater is designed around that model. It updates application-managed files and Web assets while '
          'preserving .env, projects, logs, and database configuration.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#upgrade-mental-model'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Recommended upgrade command',
  'text': 'From the installed ScipionAPI root:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update\n'
          '\n'
          'This resolves the newest release, test releases included, from the releases of ScipionWeb on GitHub '
          'first:\n'
          '\n'
          'text\n'
          'https://github.com/fonsecareyna82/ScipionWeb/releases\n'
          '\n'
          'When GitHub does not have it or does not answer, it uses the latest release of the CNB download server:\n'
          '\n'
          'text\n'
          'https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/manifest.json\n'
          '\n'
          'If the files of a release found on GitHub do not download, the same release is taken from the CNB server. '
          '--base-url (or SCIPIONAPIUPDATEBASEURL) makes the update use only the address given.\n'
          '\n'
          'The manifest identifies the matching API and Web artifacts and contains their checksum metadata.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#recommended-upgrade-command'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Preview before changing anything',
  'text': 'Always inspect the update plan first on important installations:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --dry-run\n'
          '\n'
          'A dry run resolves the target release and prints the planned changes without replacing application files, '
          'applying migrations, deploying Web assets, or restarting runtime services.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#preview-before-changing-anything'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Upgrade to a specific version',
  'text': 'bash\n'
          './scripts/scipionapi update --version v4.0.1\n'
          '\n'
          'The selected version must be present in the public release manifest or otherwise resolvable through the '
          'configured release source.\n'
          '\n'
          'Standard paired artifacts use:\n'
          '\n'
          'text\n'
          'ScipionAPI-v4.0.1.zip\n'
          'ScipionWeb-v4.0.1-dist.zip\n'
          '\n'
          'Keep API and Web versions aligned during normal upgrades.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#upgrade-to-a-specific-version'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Reinstall the same version',
  'text': 'If the installed API version already matches the target version, the updater may skip unnecessary '
          'replacement.\n'
          '\n'
          'To intentionally reinstall the same version:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --version v4.0.1 --force\n'
          '\n'
          'Use this for controlled repair or release validation, not as the normal upgrade path.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#reinstall-the-same-version'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'What the updater does',
  'text': 'A normal update can perform the following sequence:\n'
          '\n'
          '1. reads the existing installation environment and resolves SCIPIONHOME\n'
          '2. resolves the target release from the public manifest\n'
          '3. downloads the ScipionAPI and ScipionWeb ZIP files\n'
          '4. verifies published SHA256 checksums when available\n'
          '5. extracts and validates the release artifacts\n'
          '6. creates a rollback backup of managed application files\n'
          '7. stops runtime services\n'
          '8. replaces managed ScipionAPI files\n'
          '9. installs updated Python requirements/package state\n'
          '10. applies Alembic migrations\n'
          '11. redeploys the Web bundle when integrated mode is enabled\n'
          '12. restarts services unless --no-restart was requested\n'
          '13. writes update metadata back to .env\n'
          '14. keeps the configured number of filesystem backups\n'
          '\n'
          'The root install.sh is part of the managed API files, so an updated ScipionAPI release can also update '
          'the installer distributed with the installation.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#what-the-updater-does'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Runtime data preserved by update',
  'text': 'Normal update is not an uninstall. It preserves:\n'
          '\n'
          '- SCIPIONHOME\n'
          '- .env\n'
          '- projects\n'
          '- logs\n'
          '- database data/configuration\n'
          '- user/admin state stored in the database\n'
          '- the stable installation root\n'
          '\n'
          'The updater replaces only the files and Web deployment areas it manages.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#runtime-data-preserved-by-update'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Update metadata written to `.env`',
  'text': 'After a successful update, metadata can include values such as:\n'
          '\n'
          'env\n'
          'SCIPIONAPILASTUPDATEVERSION=v4.0.1\n'
          'SCIPIONAPILASTUPDATEAT=20260812T143000Z\n'
          'SCIPIONAPILASTUPDATESOURCE=https://github.com/fonsecareyna82/ScipionWeb/releases/download/v4.0.1/\n'
          '\n'
          'SCIPIONAPILASTUPDATESOURCE only records where the update came from. Set SCIPIONAPIUPDATEBASEURL yourself '
          'only to make updates use one address alone. Older updates wrote the CNB address there; that value is '
          'ignored, so they also look on GitHub first.\n'
          '\n'
          'ScipionWeb can use backend system endpoints to expose the installed version and update availability. The '
          "dashboard's check also looks on GitHub first and on the CNB server next, and waits at most 15 seconds.",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#update-metadata-written-to-env'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Update notifications in ScipionWeb',
  'text': 'The backend can check the same public manifest used by the CLI updater.\n'
          '\n'
          'Relevant endpoints include:\n'
          '\n'
          'http\n'
          'GET /api/system/version\n'
          'GET /api/system/update-check\n'
          '\n'
          'The Web UI may inform users that a newer release is available, but the actual server update should be run '
          'from a controlled shell session.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#update-notifications-in-scipionweb'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Useful update options',
  'text': 'bash\n'
          './scripts/scipionapi update --dry-run\n'
          './scripts/scipionapi update --version v4.0.1\n'
          './scripts/scipionapi update --version v4.0.1 --force\n'
          './scripts/scipionapi update --api-only\n'
          './scripts/scipionapi update --web-only\n'
          './scripts/scipionapi update --no-restart\n'
          '\n'
          'Use --api-only and --web-only for controlled maintenance/debugging. Normal releases should move API and '
          'Web together.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#useful-update-options'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Update without Internet',
  'text': "Put the new release's ScipionAPI- .zip, ScipionWeb- -dist.zip and manifest.json in a folder and point the "
          'updater at it with a file:// address:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --base-url file:///media/usb/scipionweb-v4.1.0/ --dry-run\n'
          './scripts/scipionapi update --base-url file:///media/usb/scipionweb-v4.1.0/\n'
          '\n'
          '➡️ Installing Without Internet',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#update-without-internet'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Update several machines',
  'text': 'On a multi-node installation sharing the installation folder, update once, on the main node: the nodes '
          "see the new files on the shared disk. Then restart each compute node's worker on that node:\n"
          '\n'
          'bash\n'
          './scripts/scipionapi restart\n'
          '\n'
          'A node that is restarted later keeps running the old code until then, so restart them all right after the '
          'update.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#update-several-machines'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Backup and rollback thinking',
  'text': 'The updater creates a filesystem rollback backup before replacing managed API files.\n'
          '\n'
          'If an error occurs after that point, the updater can attempt to restore managed application files. '
          'Database migrations are different: database rollback still requires a database backup when schema changes '
          'matter.\n'
          '\n'
          'For important/shared deployments:\n'
          '\n'
          '1. back up PostgreSQL\n'
          '2. run update --dry-run\n'
          '3. apply the update during a controlled maintenance window\n'
          '4. verify status, logs, login, project loading, and one basic workflow action',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#backup-and-rollback-thinking'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Manual upgrade fallback',
  'text': 'If the built-in updater cannot be used, a manual fallback remains possible:\n'
          '\n'
          '1. stop services\n'
          '2. back up PostgreSQL\n'
          '3. obtain the new matched API/Web release pair\n'
          '4. extract the new API bundle in a clean location\n'
          '5. point it to the intended existing SCIPIONHOME\n'
          '6. run provision with the matching Web bundle\n'
          '7. verify runtime and application behavior\n'
          '\n'
          'This path is more error-prone because the operator must preserve runtime paths, configuration, and '
          'version alignment explicitly.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#manual-upgrade-fallback'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Release publication and `manifest.json`',
  'text': 'Maintainers should not manually edit/upload manifest.json as part of the normal release process.\n'
          '\n'
          'The release publisher now:\n'
          '\n'
          '- downloads the current remote manifest when it exists\n'
          '- preserves previous release entries\n'
          '- adds the new release metadata and checksums\n'
          '- publishes API ZIP, Web ZIP, and install.sh\n'
          '- publishes manifest.json last\n'
          '\n'
          'See Publish a ScipionWeb Release and the release CLI reference.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#release-publication-and-manifestjson'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Common upgrade mistakes',
  'text': 'Skipping the dry run:\n'
          'On production or shared installations, inspect ./scripts/scipionapi update --dry-run before the real '
          'update.\n'
          '\n'
          'Forgetting database backups:\n'
          'The updater protects managed application files, but a database schema rollback still needs a database '
          'backup.\n'
          '\n'
          'API and Web versions drift apart:\n'
          'Keep the paired release version aligned unless you are intentionally testing a compatibility scenario.\n'
          '\n'
          'Treating an existing installation as a new install:\n'
          'Do not run a fresh install.sh over an existing installation directory. Use the installed update command.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#common-upgrade-mistakes'},
 {'area': 'installation',
  'page': 'Upgrade Guide',
  'title': 'Guided-install users',
  'text': 'If the original installation was created through the guided install.sh, nothing special is required for '
          'normal upgrades:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi update --dry-run\n'
          '/path/to/scipionweb/scripts/scipionapi update\n'
          '\n'
          'The guided installation marker remains useful later for protected full uninstall; it does not change the '
          'normal update workflow.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/installation/upgrade/#guided-install-users'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'What is configured here',
  'text': 'Common configuration groups include:\n'
          '\n'
          '- PostgreSQL connection/bootstrap values\n'
          '- application secret key\n'
          '- API host and selected port\n'
          '- Valkey/Celery settings\n'
          '- logs/projects/runtime paths\n'
          '- integrated Web deployment settings\n'
          '- Conda executable/activation metadata\n'
          '- update metadata\n'
          '\n'
          'The exact set evolves with ScipionAPI versions. Treat the installed CLI/code as authoritative for '
          'supported keys.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#what-is-configured-here'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Database settings',
  'text': 'Typical values include:\n'
          '\n'
          'dotenv\n'
          'DATABASEURL=postgresql://user:password@host:5432/database\n'
          'DATABASENAME=scipiondb\n'
          'DATABASEUSER=scipionuser\n'
          'DATABASEPASS=\n'
          '\n'
          'Keep the split database values consistent with DATABASEURL when both are present. Inconsistent values can '
          'make bootstrap, administration, and runtime connectivity behave differently.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#database-settings'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Security',
  'text': 'A strong application secret is required:\n'
          '\n'
          'dotenv\n'
          'SECRETKEY=\n'
          '\n'
          'Use a long private value and protect the .env file from unauthorized reading.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#security'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'API runtime',
  'text': 'Typical runtime keys include:\n'
          '\n'
          'dotenv\n'
          'APIHOST=0.0.0.0\n'
          'APIPORT=\n'
          '\n'
          'Automatic port selection\n'
          '\n'
          'Do not assume that new installations always use port 8080.\n'
          '\n'
          'When install/provision is called without --api-port:\n'
          '\n'
          '1. an existing configured APIPORT is preserved when appropriate\n'
          '2. otherwise a free port is selected automatically\n'
          '3. that value is persisted in .env\n'
          '\n'
          'Read the actual value:\n'
          '\n'
          'bash\n'
          'grep \'^APIPORT=\' "$SCIPIONHOME/.env"\n'
          '\n'
          'If a fixed port is operationally required, pass --api-port PORT during installation/provisioning.\n'
          '\n'
          'Reverse proxy deployments:\n'
          'The selected API port can remain an internal service port behind nginx/Apache or another reverse proxy. '
          'Public HTTPS exposure does not require hardcoding a particular backend port in the release bundle.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#api-runtime'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Valkey / Celery',
  'text': 'Typical broker configuration:\n'
          '\n'
          'dotenv\n'
          'BROKERURL=redis://localhost:6379/0\n'
          'CELERYLOGLEVEL=info\n'
          '\n'
          'Valkey must remain reachable for Celery background processing.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#valkey-celery'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Multi-node deployment',
  'text': 'These are only needed on several machines; an ordinary single-node installation does not need any of '
          'them. scipionapi multinode enable and scipionapi node join write them for you.\n'
          '\n'
          'dotenv\n'
          'SCIPIONAPIDEPLOYMENTMODE=multi-node\n'
          'PROTOCOLSCELERYQUEUE=protocols-gpu\n'
          '\n'
          '- SCIPIONAPIDEPLOYMENTMODE — set on every node to multi-node so ./scripts/scipionapi doctor --strict '
          'escalates loopback broker/database URLs and a non-shared PROJECTSPATH from warnings to failures. Defaults '
          'to single-node behavior when unset.\n'
          "- PROTOCOLSCELERYQUEUE — persists a custom Celery queue name for that node's protocol worker (equivalent "
          'to runtime start --role protocols --queue  , but also honored when the worker is restarted from the web '
          'UI). Defaults to protocols.\n'
          '\n'
          "- SCIPIONAPIMAINNODE and SCIPIONAPIMULTINODENETWORK — written by multinode enable: the main node's name "
          "(a node never joins as itself) and the nodes' network.\n"
          '- POSTGRESHOST / POSTGRESPORT — the database server the API and every worker connect to. localhost on one '
          "machine; the main node's network name on several.\n"
          '\n'
          "A compute node's own values live in its profile, scipionhome/nodes/ .env, read over the shared .env on "
          'that machine only (written by node join):\n'
          '\n'
          '| Variable | Meaning |\n'
          '|---|---|\n'
          '| SCIPIONAPINODEROLE | What start runs there: protocols |\n'
          "| PROTOCOLSCELERYQUEUE | The node's queue |\n"
          '| PROTOCOLWORKERCONCURRENCY | Protocols the machine runs at once, of all users (default 12; a protocol in '
          'streaming keeps its place all along). Not the same as Max concurrent runs per user (Settings → Instance), '
          'which shares them out among users |\n'
          '| LOGSPATH | scipionhome/logs/nodes/  |',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#multi-node-deployment'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Runtime filesystem paths',
  'text': 'Examples:\n'
          '\n'
          'dotenv\n'
          'LOGSPATH=/path/to/scipionhome/logs\n'
          'PROJECTSPATH=/path/to/scipionhome/projects\n'
          '\n'
          'Depending on the installation version, paths may be absolute or resolved from the runtime workspace. '
          'Ensure the service user owns/has write access to the required runtime directories.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#runtime-filesystem-paths'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Integrated Web mode',
  'text': 'Integrated deployments commonly include:\n'
          '\n'
          'dotenv\n'
          'SERVEWEB=1\n'
          'APIMOUNTPATH=/api\n'
          'WEBDISTPATH=/path/to/scipionhome/web/dist\n'
          'WEBAPIBASEURL=/api\n'
          '\n'
          'Roles:\n'
          '\n'
          '- SERVEWEB=1 enables frontend serving from ScipionAPI\n'
          '- APIMOUNTPATH controls where the REST API is mounted\n'
          '- WEBDISTPATH identifies the deployed compiled frontend\n'
          '- WEBAPIBASEURL tells the Web UI which API base path/URL to use\n'
          '\n'
          'For the normal integrated configuration, APIMOUNTPATH and WEBAPIBASEURL are usually both /api.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#integrated-web-mode'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Conda integration',
  'text': 'Provisioning can persist Conda information such as:\n'
          '\n'
          'dotenv\n'
          'CONDAEXE=/home/user/miniconda3/bin/conda\n'
          'CONDAACTIVATIONCMD=...\n'
          '\n'
          'These values depend on the real Conda installation and should generally be managed by the '
          'provisioning/bootstrap flow rather than guessed manually.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#conda-integration'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Administrator bootstrap metadata',
  'text': 'The installation flow can persist non-secret administrator identity metadata when useful, for example '
          'username/email depending on release behavior.\n'
          '\n'
          'Administrator passwords should be supplied through hidden prompts or temporary environment variables such '
          'as those used by the installer/CLI.\n'
          '\n'
          'Do not rely on plaintext admin passwords in .env:\n'
          'The normal password flow uses the password to create/update the account. Do not add ADMINPASSWORD=  to '
          '.env as an operational shortcut.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#administrator-bootstrap-metadata'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Update metadata',
  'text': 'Successful updates can record metadata such as:\n'
          '\n'
          'dotenv\n'
          'SCIPIONAPILASTUPDATEVERSION=v4.0.1\n'
          'SCIPIONAPILASTUPDATEAT=20260812T143000Z\n'
          'SCIPIONAPIUPDATEBASEURL=https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/\n'
          '\n'
          'This helps the backend/UI describe installed release state and update availability.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#update-metadata'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Example integrated `.env`',
  'text': 'The exact generated values depend on the installation, but conceptually:\n'
          '\n'
          'dotenv\n'
          'DATABASEURL=postgresql://scipionuser: @localhost:5432/scipiondb\n'
          'DATABASENAME=scipiondb\n'
          'DATABASEUSER=scipionuser\n'
          'DATABASEPASS=\n'
          '\n'
          'SECRETKEY=\n'
          '\n'
          'APIHOST=0.0.0.0\n'
          'APIPORT=39080\n'
          '\n'
          'BROKERURL=redis://localhost:6379/0\n'
          'CELERYLOGLEVEL=info\n'
          '\n'
          'LOGSPATH=/home/user/scipionweb/scipionhome/logs\n'
          'PROJECTSPATH=/home/user/scipionweb/scipionhome/projects\n'
          '\n'
          'SERVEWEB=1\n'
          'APIMOUNTPATH=/api\n'
          'WEBDISTPATH=/home/user/scipionweb/scipionhome/web/dist\n'
          'WEBAPIBASEURL=/api\n'
          '\n'
          '39080 is only an example. Read the real APIPORT generated for your installation.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#example-integrated-env'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Loading `.env` in a shell',
  'text': 'When an administrative workflow genuinely needs the variables exported into the current shell:\n'
          '\n'
          'bash\n'
          'set -a\n'
          'source "$SCIPIONHOME/.env"\n'
          'set +a\n'
          '\n'
          'Be careful when doing this in shared shells because secrets become environment variables for child '
          'processes.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#loading-env-in-a-shell'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Back up configuration',
  'text': 'Before significant manual configuration or database changes:\n'
          '\n'
          'bash\n'
          'cp "$SCIPIONHOME/.env" "$SCIPIONHOME/.env.backup"\n'
          '\n'
          'For normal managed upgrades, the updater is designed to preserve the runtime workspace/configuration, but '
          'keeping an administrative backup remains sensible for important systems.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#back-up-configuration'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Permissions',
  'text': 'A common restrictive configuration is:\n'
          '\n'
          'bash\n'
          'chmod 600 "$SCIPIONHOME/.env"\n'
          '\n'
          'Ensure ownership matches the account that operates ScipionWeb.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#permissions'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Common mistakes',
  'text': 'Assuming port 8080:\n'
          'Resolve APIPORT from .env or runtime output. Automatic port selection is intentional.\n'
          '\n'
          'Stale WEBDISTPATH:\n'
          'If Web assets are moved manually, integrated mode can point to old content. Normal update/deployment '
          'commands should manage the Web distribution path for you.\n'
          '\n'
          'Mismatched API paths:\n'
          'In integrated mode, keep APIMOUNTPATH and WEBAPIBASEURL aligned unless a custom topology requires '
          'otherwise.\n'
          '\n'
          'Database values disagree:\n'
          'Avoid inconsistent DATABASEURL, database name, user, or password settings.\n'
          '\n'
          'Editing generated Conda settings casually:\n'
          'Test status, doctor, and restart after any manual change to Conda/runtime configuration.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#common-mistakes'},
 {'area': 'configuration',
  'page': 'Environment Variables (`.env`)',
  'title': 'Quick verification',
  'text': 'bash\n'
          'test -f "$SCIPIONHOME/.env" && echo ".env found"\n'
          "grep -E '^(DATABASEURL|APIHOST|APIPORT|BROKERURL|SERVEWEB|APIMOUNTPATH|WEBDISTPATH)=' \\\n"
          '"$SCIPIONHOME/.env" || true\n'
          '\n'
          'Then verify the runtime using the persisted port:\n'
          '\n'
          'bash\n'
          'APIPORT="$(grep \'^APIPORT=\' "$SCIPIONHOME/.env" | tail -n 1 | cut -d= -f2-)"\n'
          'curl "http://localhost:${APIPORT}/health"\n'
          '\n'
          'Finally:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi status\n'
          './scripts/scipionapi doctor --quick',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/env/#quick-verification'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'Overview',
  'text': 'In the standard integrated configuration:\n'
          '\n'
          '- Web UI is served at /\n'
          '- API is mounted under /api\n'
          '- API docs are available under /api/docs\n'
          '\n'
          'The host port is runtime configuration, not a fixed release property.\n'
          '\n'
          'Read the actual port from the installed environment:\n'
          '\n'
          'bash\n'
          'grep \'^APIPORT=\' "$SCIPIONHOME/.env"\n'
          '\n'
          'Then the normal URLs are:\n'
          '\n'
          'text\n'
          'http://localhost: /\n'
          'http://localhost: /api/docs\n'
          '\n'
          'Automatic port selection:\n'
          'When no fixed --api-port is supplied, provisioning can select a free port automatically and persist it in '
          '.env.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#overview'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'Recommended installation path',
  'text': 'For a new integrated installation:\n'
          '\n'
          'bash\n'
          'wget https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/install.sh\n'
          'chmod +x install.sh\n'
          './install.sh --check-only\n'
          './install.sh\n'
          '\n'
          'The installer resolves a paired API + Web release, verifies checksums, and delegates integrated runtime '
          'setup to provision.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#recommended-installation-path'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'Direct/manual integrated provision',
  'text': 'Advanced users can deploy a specific compiled Web artifact directly:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org" \\\n'
          '--web-dist /path/to/ScipionWeb-vX.Y.Z-dist.zip\n'
          '\n'
          'During provisioning, ScipionAPI deploys the Web assets under the runtime workspace and configures the '
          'frontend/API relationship.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#directmanual-integrated-provision'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'Runtime behavior',
  'text': 'With integrated mode enabled:\n'
          '\n'
          'text\n'
          '/             → compiled ScipionWeb frontend\n'
          '/api/...      → REST API\n'
          '/api/docs     → OpenAPI/Swagger documentation\n'
          '\n'
          'Example using the real configured port:\n'
          '\n'
          'bash\n'
          'APIPORT="$(grep \'^APIPORT=\' "$SCIPIONHOME/.env" | tail -n 1 | cut -d= -f2-)"\n'
          '\n'
          'curl "http://localhost:${APIPORT}/health"\n'
          '\n'
          'Open:\n'
          '\n'
          'text\n'
          'http://localhost: /\n'
          'http://localhost: /api/docs',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#runtime-behavior'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'Important `.env` settings',
  'text': 'A typical integrated installation includes:\n'
          '\n'
          'dotenv\n'
          'SERVEWEB=1\n'
          'APIMOUNTPATH=/api\n'
          'WEBDISTPATH=/path/to/scipionhome/web/dist\n'
          'WEBAPIBASEURL=/api\n'
          'APIPORT=\n'
          '\n'
          'Roles:\n'
          '\n'
          '- SERVEWEB=1 enables frontend serving\n'
          '- APIMOUNTPATH controls where the REST API is mounted\n'
          '- WEBDISTPATH identifies the deployed frontend files\n'
          '- WEBAPIBASEURL tells the frontend where to call the API\n'
          '- APIPORT is the persisted listening port\n'
          '\n'
          'In the normal configuration, APIMOUNTPATH and WEBAPIBASEURL are both /api.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#important-env-settings'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'Runtime frontend configuration',
  'text': 'The compiled Web build is designed to be reusable across installations.\n'
          '\n'
          'ScipionAPI injects/deploys runtime API configuration so the same Web release does not need to be rebuilt '
          'for every host or selected port.\n'
          '\n'
          'This means:\n'
          '\n'
          '- release ZIPs remain installation-independent\n'
          '- automatic port selection does not require rebuilding ScipionWeb\n'
          '- reverse proxies can be introduced without publishing a new frontend artifact',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#runtime-frontend-configuration'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'When integrated mode is a good fit',
  'text': 'Use it for:\n'
          '\n'
          '- normal guided installations\n'
          '- single-host deployments\n'
          '- local/on-prem installations\n'
          '- internal lab servers\n'
          '- deployments where operational simplicity matters\n'
          '\n'
          'Advantages include:\n'
          '\n'
          '- same-origin API/UI traffic\n'
          '- simple networking\n'
          '- no separate static Web host requirement\n'
          '- one update path for paired API + Web releases',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#when-integrated-mode-is-a-good-fit'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'When to use a separate deployment',
  'text': 'A separate frontend/backend topology may be appropriate when:\n'
          '\n'
          '- Web assets are served by a CDN/static host\n'
          '- API and frontend scale independently\n'
          '- network/security zones require separation\n'
          '- an existing infrastructure already provides static frontend hosting\n'
          '\n'
          'See Separate Deployment.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#when-to-use-a-separate-deployment'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'Verify integrated mode',
  'text': '1. Runtime status\n'
          '\n'
          'bash\n'
          './scripts/scipionapi status\n'
          './scripts/scipionapi doctor --quick\n'
          '\n'
          '2. Resolve the actual port\n'
          '\n'
          'bash\n'
          'APIPORT="$(grep \'^APIPORT=\' "$SCIPIONHOME/.env" | tail -n 1 | cut -d= -f2-)"\n'
          'echo "$APIPORT"\n'
          '\n'
          '3. Health endpoint\n'
          '\n'
          'bash\n'
          'curl "http://localhost:${APIPORT}/health"\n'
          '\n'
          '4. Browser\n'
          '\n'
          'Open:\n'
          '\n'
          'text\n'
          'http://localhost: /\n'
          'http://localhost: /api/docs\n'
          '\n'
          '5. Browser network requests\n'
          '\n'
          'Confirm API requests use the expected /api/... base path.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#verify-integrated-mode'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'Common issues',
  'text': 'Frontend loads but API calls fail:\n'
          'Check APIMOUNTPATH, WEBAPIBASEURL, and any reverse-proxy path rewriting.\n'
          '\n'
          'Using the wrong port:\n'
          'Read APIPORT from .env; do not assume 8080 unless you explicitly configured it.\n'
          '\n'
          'Stale Web assets:\n'
          'Use the managed update/deployment workflow so WEBDISTPATH points to the intended deployed release.\n'
          '\n'
          'Opening /docs instead of /api/docs:\n'
          'In the standard integrated configuration, API documentation is under the API mount path.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#common-issues'},
 {'area': 'configuration',
  'page': 'API + Web Integrated Mode',
  'title': 'Updating integrated mode',
  'text': 'For an installed system:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --dry-run\n'
          './scripts/scipionapi update\n'
          '\n'
          'The updater resolves the paired release from manifest.json, verifies checksums, updates managed API '
          'files, and redeploys the Web bundle while preserving SCIPIONHOME.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/integrated-mode/#updating-integrated-mode'},
 {'area': 'configuration',
  'page': 'SCIPION_HOME and Runtime Layout',
  'title': 'Default Location',
  'text': 'If SCIPIONHOME is not set explicitly, ScipionAPI typically uses:\n'
          '\n'
          'text\n'
          'SCIPIONHOME= /scipionhome\n'
          '\n'
          'You can override it by exporting the variable before starting the application:\n'
          '\n'
          'export SCIPIONHOME=/opt/scipionweb/runtime\n'
          '\n'
          'Production recommendation:\n'
          'In production, use a dedicated path outside the API bundle directory (for example '
          '/opt/scipionweb/runtime) so upgrades do not affect runtime data.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/scipion-home/#default-location'},
 {'area': 'configuration',
  'page': 'SCIPION_HOME and Runtime Layout',
  'title': 'Typical Directory Structure',
  'text': 'Example layout:\n'
          '\n'
          'text\n'
          'scipionhome/\n'
          '├── .env\n'
          '├── logs/\n'
          '│   ├── app.log\n'
          '│   ├── celery.log\n'
          '│   ├── celery-protocols.log\n'
          "│   └── nodes/ /            (compute nodes' logs)\n"
          '├── projects/\n'
          "│   ├──  /          (new projects, in their owner's folder)\n"
          '│   └──          (projects made before)\n'
          '├── config/\n'
          '│   ├── hosts.conf\n'
          '│   └── celeryqueuerouting.json  (several machines: Scipion host → queue)\n'
          "├── nodes/ .env             (several machines: each compute node's profile)\n"
          '├── multinode/backup- /     (what multinode enable changed, before it changed it)\n'
          '└── web/\n'
          '└── dist/\n'
          '\n'
          'Mode-dependent directories:\n'
          'The web/ directory is typically present only in integrated mode (when the API serves the Web UI).',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/scipion-home/#typical-directory-structure'},
 {'area': 'configuration',
  'page': 'SCIPION_HOME and Runtime Layout',
  'title': 'What Each Path Is Used For',
  'text': '.env\n'
          '\n'
          'Primary runtime configuration file.\n'
          '\n'
          'It typically contains:\n'
          '\n'
          '- Database connection settings\n'
          '- Security-related values (for example SECRETKEY)\n'
          '- Runtime paths\n'
          '- Deployment mode flags\n'
          '- API and broker configuration\n'
          '\n'
          'Sensitive file:\n'
          'The .env file may contain credentials and secrets. Protect file permissions and never commit it to '
          'version control.\n'
          '\n'
          'logs/\n'
          '\n'
          'Stores runtime logs, commonly including:\n'
          '\n'
          '- API logs\n'
          '- Celery worker logs\n'
          '\n'
          'Typical uses:\n'
          '\n'
          '- Debugging errors\n'
          '- Operational monitoring\n'
          '- Post-incident inspection\n'
          '\n'
          'Log rotation:\n'
          'In production, plan a log rotation strategy (system-managed logs, logrotate, or journald-based logging '
          'depending on your deployment approach).\n'
          '\n'
          'projects/\n'
          '\n'
          'Stores project runtime data, such as:\n'
          '\n'
          '- Scipion projects\n'
          '- Generated previews\n'
          '- Runtime artifacts\n'
          '\n'
          "Each user's new projects go into a folder of their own, projects/ /, named after their email "
          "(ana@cnb.csic.es → ana), as Scipion's ScipionUserData does for each Linux user. Projects made before stay "
          'where they are.\n'
          '\n'
          'This directory can grow significantly over time depending on project size and usage patterns. Settings → '
          'Usage → Disk shows how much each user, group and project takes.\n'
          '\n'
          'Disk usage growth:\n'
          'Monitor available disk space and define a backup/retention strategy, especially for production or shared '
          'environments.\n'
          '\n'
          'config/\n'
          '\n'
          'Optional location for Scipion-related runtime configuration files and generated configuration state, '
          'depending on your deployment and tooling.\n'
          '\n'
          'Contents may vary:\n'
          'The exact contents of config/ may differ across versions or deployment workflows.\n'
          '\n'
          'web/\n'
          '\n'
          'Present when using integrated mode.\n'
          '\n'
          'Typical contents:\n'
          '\n'
          'text\n'
          'web/dist/\n'
          'index.html\n'
          'assets/\n'
          'config.js\n'
          '\n'
          'This directory stores the deployed frontend assets served by the API.\n'
          '\n'
          'Web bundle upgrades:\n'
          'When upgrading the integrated Web UI, the deployed contents under web/ may be replaced by a new '
          '--web-dist deployment.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/scipion-home/#what-each-path-is-used-for'},
 {'area': 'configuration',
  'page': 'SCIPION_HOME and Runtime Layout',
  'title': 'Permissions and Ownership',
  'text': 'Ensure that the service user (or the user running ScipionAPI) has the correct access to SCIPIONHOME.\n'
          '\n'
          'Minimum recommendations:\n'
          '\n'
          '- Read/write access to SCIPIONHOME\n'
          '- Write access to logs/, projects/, and deployed runtime paths\n'
          '- Read access to .env\n'
          '- Enough free disk space for project growth and logs\n'
          '\n'
          'Permission mismatches:\n'
          'Avoid mixing root-owned files with services running as a non-root user. This is a common cause of startup '
          'failures and runtime write errors.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/scipion-home/#permissions-and-ownership'},
 {'area': 'configuration',
  'page': 'SCIPION_HOME and Runtime Layout',
  'title': 'Backup Strategy',
  'text': 'A practical backup strategy should include:\n'
          '\n'
          '- PostgreSQL database backup\n'
          '- Entire scipionhome/projects/ directory\n'
          '- SCIPIONHOME/.env\n'
          '- Any deployment-specific runtime configuration you rely on\n'
          '\n'
          'Upgrade safety:\n'
          'Before upgrading ScipionAPI/ScipionWeb, back up both the database and key SCIPIONHOME contents so you can '
          'recover configuration and project data if needed.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/scipion-home/#backup-strategy'},
 {'area': 'configuration',
  'page': 'SCIPION_HOME and Runtime Layout',
  'title': 'Production Recommendations',
  'text': 'For production deployments, prefer a dedicated runtime path such as:\n'
          '\n'
          'text\n'
          '/opt/scipionweb/runtime\n'
          '\n'
          'instead of storing runtime data inside the API source or extracted bundle directory.\n'
          '\n'
          'Recommended practices:\n'
          '\n'
          '- Keep SCIPIONHOME outside version-controlled directories\n'
          '- Protect .env permissions\n'
          '- Monitor disk usage in projects/ and logs/\n'
          '- Back up runtime data regularly\n'
          '- Reuse the same SCIPIONHOME across API bundle upgrades (when appropriate)',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/scipion-home/#production-recommendations'},
 {'area': 'configuration',
  'page': 'SCIPION_HOME and Runtime Layout',
  'title': 'Common Mistakes',
  'text': 'Using a temporary directory:\n'
          'Do not place SCIPIONHOME under /tmp or other ephemeral locations. You may lose logs, configuration, and '
          'project data.\n'
          '\n'
          'Forgetting to export SCIPIONHOME after upgrade:\n'
          'If you move to a new API bundle directory and forget to export the existing SCIPIONHOME, the application '
          'may create a new empty runtime workspace and appear misconfigured.\n'
          '\n'
          'Committing runtime files:\n'
          'Avoid committing scipionhome/ or .env files into Git repositories.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/scipion-home/#common-mistakes'},
 {'area': 'configuration',
  'page': 'SCIPION_HOME and Runtime Layout',
  'title': 'Quick Verification',
  'text': 'Run these checks to confirm the runtime workspace is correctly configured:\n'
          '\n'
          'echo "$SCIPIONHOME"\n'
          'ls -al "$SCIPIONHOME"\n'
          'test -f "$SCIPIONHOME/.env" && echo ".env found"\n'
          'test -d "$SCIPIONHOME/projects" && echo "projects/ found"\n'
          'test -d "$SCIPIONHOME/logs" && echo "logs/ found"\n'
          '\n'
          'If a path is missing:\n'
          'Some directories may be created lazily depending on how the application is used. The most critical item '
          'to verify early is SCIPIONHOME/.env.\n'
          '\n'
          '← Previous: Configuration Overview\n'
          '\n'
          'Next: Environment Variables (.env) →',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/scipion-home/#quick-verification'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Architecture Overview',
  'text': 'A simplified request flow looks like this:\n'
          '\n'
          'text\n'
          'User Browser → Web Server / CDN → REST API → PostgreSQL / Valkey\n'
          '\n'
          'In practice:\n'
          '\n'
          '- The browser loads the frontend from a web host (or CDN)\n'
          '- The frontend sends API requests to the ScipionAPI host\n'
          '- The API talks to PostgreSQL and Valkey',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#architecture-overview'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'When to Use Separate Deployment',
  'text': 'This mode is recommended for:\n'
          '\n'
          '- Production environments\n'
          '- Cloud deployments\n'
          '- Enterprise setups\n'
          '- Load-balanced infrastructure\n'
          '- CDN/static hosting for the frontend\n'
          '- Teams that deploy frontend and backend independently\n'
          '\n'
          'Best for scale and flexibility:\n'
          'If you need independent release cycles or web performance optimization, separate deployment is usually '
          'the better choice.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#when-to-use-separate-deployment'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Frontend Configuration',
  'text': 'The frontend must know the public base URL of the API.\n'
          '\n'
          'Frontend .env (example)\n'
          '\n'
          'dotenv\n'
          'VITEAPIURL="https://api.yourdomain.com"\n'
          '\n'
          'Frontend config usage example\n'
          '\n'
          'ts\n'
          'export const BASEURL = import.meta.env.VITEAPIURL;\n'
          '\n'
          'After changing frontend environment variables, rebuild (or redeploy) the frontend.\n'
          '\n'
          'Rebuild required:\n'
          'For most Vite-based frontends, environment variables are injected at build time. Changing VITEAPIURL '
          'usually requires a rebuild.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#frontend-configuration'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'API Configuration',
  'text': 'In separate deployment mode, the API should not serve the frontend.\n'
          '\n'
          'Disable integrated mode\n'
          '\n'
          'dotenv\n'
          'SERVEWEB=0\n'
          '\n'
          'CORS configuration\n'
          '\n'
          'The API must allow the frontend origin(s). Example backend configuration:\n'
          '\n'
          'python\n'
          'alloworigins=["http://web-host:5173"]\n'
          '\n'
          'Production example:\n'
          '\n'
          'python\n'
          'alloworigins=["https://yourdomain.com"]\n'
          '\n'
          'CORS is required:\n'
          'If CORS is not configured correctly, browser requests may fail even when the API is healthy and '
          'reachable.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#api-configuration'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Production Example',
  'text': 'API server\n'
          '\n'
          'text\n'
          'https://api.yourdomain.com\n'
          '\n'
          'Web server (frontend)\n'
          '\n'
          'text\n'
          'https://yourdomain.com\n'
          '\n'
          'Example API request from the frontend\n'
          '\n'
          'text\n'
          'https://api.yourdomain.com/api/projects\n'
          '\n'
          'Consistent public URLs:\n'
          "Keep the frontend's configured API URL aligned with the actual public API endpoint exposed through your "
          'reverse proxy / load balancer.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#production-example'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Networking and Security Considerations',
  'text': 'TLS / HTTPS\n'
          '\n'
          'Use HTTPS on both sides in production:\n'
          '\n'
          '- Frontend host (web app)\n'
          '- API host (backend)\n'
          '\n'
          'Firewalls / security groups\n'
          '\n'
          'Allow inbound access only to what is needed:\n'
          '\n'
          '- Public web ports (80 / 443) on frontend host\n'
          '- Public or controlled access to API host (usually 443 behind a reverse proxy)\n'
          '- Internal database/Valkey access restricted to trusted hosts/services\n'
          '\n'
          'Reverse proxy alignment\n'
          '\n'
          'If the API is mounted under /api, ensure your reverse proxy configuration preserves the expected path.\n'
          '\n'
          'Path rewrite mistakes:\n'
          'Misconfigured reverse proxies can strip or duplicate /api, causing 404s even though the backend is '
          'running.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#networking-and-security-considerations'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Advantages',
  'text': '- Independent scaling of frontend and backend\n'
          '- CDN support and static hosting optimization\n'
          '- Better frontend performance at scale\n'
          '- Clear separation of concerns\n'
          '- Independent deployment pipelines',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#advantages'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Considerations and Tradeoffs',
  'text': '- CORS configuration is required\n'
          '- SSL/TLS must be configured correctly\n'
          '- More moving parts than integrated mode\n'
          '- DNS, proxy, and firewall configuration become part of deployment operations\n'
          '\n'
          'Operational complexity vs flexibility:\n'
          'Separate deployment adds infrastructure complexity, but it pays off in flexibility and scalability for '
          'larger environments.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#considerations-and-tradeoffs'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Recommended Configuration Checklist',
  'text': 'Frontend\n'
          '\n'
          '- [ ] VITEAPIURL points to the correct public API URL\n'
          '- [ ] Frontend rebuilt/redeployed after env changes\n'
          '- [ ] HTTPS enabled on the frontend host\n'
          '\n'
          'API\n'
          '\n'
          '- [ ] SERVEWEB=0\n'
          '- [ ] CORS allows the frontend origin(s)\n'
          '- [ ] API mounted and proxied correctly (for example /api)\n'
          '- [ ] HTTPS enabled on the public API endpoint\n'
          '\n'
          'Infrastructure\n'
          '\n'
          '- [ ] DNS resolves frontend and API domains correctly\n'
          '- [ ] Firewall/security groups allow required traffic only\n'
          '- [ ] Reverse proxy forwards API paths as expected',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#recommended-configuration-checklist'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Verification Steps',
  'text': '1. Check API health directly\n'
          '\n'
          'curl https://api.yourdomain.com/health\n'
          '\n'
          '(adjust the URL/path to your actual public API endpoint)\n'
          '\n'
          '2. Test a browser session\n'
          '\n'
          '- Open the frontend URL\n'
          '- Log in (if applicable)\n'
          '- Open browser developer tools\n'
          '- Confirm API requests go to the expected API domain/path\n'
          '\n'
          '3. Validate CORS behavior\n'
          '\n'
          'Look for browser console/network errors such as blocked cross-origin requests.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#verification-steps'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Common Issues',
  'text': 'CORS error in browser:\n'
          'The frontend origin is missing from the backend CORS allow list (or the scheme/port does not match '
          'exactly).\n'
          '\n'
          'Frontend still calls old API host:\n'
          'VITEAPIURL was changed but the frontend was not rebuilt/redeployed.\n'
          '\n'
          'API reachable from curl but not from browser:\n'
          'This usually indicates a CORS issue, mixed-content issue (HTTPS page calling HTTP API), or an incorrect '
          'frontend API base URL.\n'
          '\n'
          '404 on /api/... behind reverse proxy:\n'
          'Check proxy path forwarding and backend mount path alignment.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#common-issues'},
 {'area': 'configuration',
  'page': 'Separate Deployment (API and Web on Different Hosts)',
  'title': 'Integrated vs Separate Deployment (Quick Comparison)',
  'text': 'Integrated Mode\n'
          '\n'
          '- Simpler setup\n'
          '- Single host / single endpoint\n'
          '- No CORS in common deployments\n'
          '- Easier for local/internal use\n'
          '\n'
          'Separate Deployment\n'
          '\n'
          '- More flexible and scalable\n'
          '- Frontend and API deploy independently\n'
          '- CORS and proxy configuration required\n'
          '- Better fit for cloud/production platforms\n'
          '\n'
          '← Previous: API + Web Integrated Mode',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/configuration/separate-deployment/#integrated-vs-separate-deployment-quick-comparison'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'What Must Be Backed Up',
  'text': 'PostgreSQL Database\n'
          '\n'
          'The database stores application metadata such as:\n'
          '\n'
          '- Users\n'
          '- Project metadata\n'
          '- Protocol metadata\n'
          '- Sharing information\n'
          '- Settings\n'
          '- Tags\n'
          '\n'
          'SCIPIONHOME\n'
          '\n'
          'The runtime workspace stores operational data such as:\n'
          '\n'
          '- projects/\n'
          '- logs/\n'
          '- config/\n'
          '- web/\n'
          '- .env\n'
          '\n'
          'Keep backups separate:\n'
          'Store database dumps and filesystem archives as separate artifacts. This makes restores and validation '
          'easier.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#what-must-be-backed-up'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Backup Strategy Overview',
  'text': 'Recommended baseline strategy:\n'
          '\n'
          '- Daily PostgreSQL backups\n'
          '- Weekly SCIPIONHOME filesystem backups\n'
          '- Off-site / external storage\n'
          '- Regular restore testing (do not skip this)\n'
          '\n'
          '| Backup Component | Frequency | Why It Matters |\n'
          '|---|---:|---|\n'
          '| PostgreSQL dump | Daily | Protects users, metadata, settings, tags |\n'
          '| SCIPIONHOME archive | Weekly (or daily in active systems) | Protects projects, logs, runtime config, '
          '.env |\n'
          '| Restore verification | Scheduled | Confirms backups are actually usable |',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#backup-strategy-overview'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Backup the Database',
  'text': 'Plain SQL dump\n'
          '\n'
          'pgdump -U scipionuser scipiondb > scipionbackup.sql\n'
          '\n'
          'Compressed dump\n'
          '\n'
          'pgdump -U scipionuser scipiondb | gzip > scipionbackup.sql.gz\n'
          '\n'
          'Compressed backups:\n'
          'Compressed dumps are usually better for storage efficiency and transfer.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#backup-the-database'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Backup `SCIPION_HOME`',
  'text': 'Create a compressed archive:\n'
          '\n'
          'tar -czf scipionhomebackup.tar.gz scipionhome/\n'
          '\n'
          'If your SCIPIONHOME lives elsewhere, use the absolute path:\n'
          '\n'
          'tar -czf scipionhomebackup.tar.gz /opt/scipionweb/scipionhome/',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#backup-scipion_home'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Full Backup Script Example',
  'text': 'Minimal one-shot example:\n'
          '\n'
          'pgdump -U scipionuser scipiondb | gzip > dbbackup.sql.gz\n'
          'tar -czf scipionhomebackup.tar.gz scipionhome/\n'
          '\n'
          'Store backups outside the host:\n'
          'Keep copies in a secure external location (separate disk, backup server, object storage, etc.). Backups '
          'on the same machine are not enough for disaster recovery.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#full-backup-script-example'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Restore Workflow Overview',
  'text': 'Recommended restore order:\n'
          '\n'
          '1. Restore database\n'
          '2. Restore SCIPIONHOME\n'
          '3. Validate .env and permissions\n'
          '4. Start services\n'
          '5. Verify /health and logs\n'
          '\n'
          'Restore to staging first:\n'
          'When possible, test recovery in an isolated environment before touching production.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#restore-workflow-overview'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Restore the Database',
  'text': 'Step 1: Create an empty database\n'
          '\n'
          'createdb -U scipionuser scipiondb\n'
          '\n'
          'Step 2: Restore from plain SQL dump\n'
          '\n'
          'psql -U scipionuser scipiondb < scipionbackup.sql\n'
          '\n'
          'Step 3: Restore from compressed dump (if applicable)\n'
          '\n'
          'gunzip -c dbbackup.sql.gz | psql -U scipionuser scipiondb\n'
          '\n'
          'Existing database:\n'
          'If the target database already exists and contains data, ensure you are restoring into the correct target '
          'and expected state before executing restore commands.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#restore-the-database'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Restore `SCIPION_HOME`',
  'text': 'Extract the archive:\n'
          '\n'
          'tar -xzf scipionhomebackup.tar.gz\n'
          '\n'
          'Ensure the service user can read/write the restored workspace:\n'
          '\n'
          'chmod -R u+rw scipionhome\n'
          '\n'
          'If using a dedicated service account, also fix ownership as needed:\n'
          '\n'
          'chown -R youruser:yourgroup scipionhome',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#restore-scipion_home'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Post-Restore Validation',
  'text': 'After restoring both components:\n'
          '\n'
          '1. Verify .env exists and matches the intended deployment\n'
          '2. Confirm SECRETKEY consistency\n'
          '3. Start services\n'
          '4. Check health endpoint\n'
          '5. Inspect logs\n'
          '\n'
          'Health check\n'
          '\n'
          'curl http://localhost:8080/health\n'
          '\n'
          'Expected:\n'
          '\n'
          'json\n'
          '{"status":"ok"}\n'
          '\n'
          'Runtime checks\n'
          '\n'
          './scripts/scipionapi status\n'
          './scripts/scipionapi logs',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#post-restore-validation'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Disaster Recovery Checklist',
  'text': 'Use this checklist during incidents:\n'
          '\n'
          '- [ ] Restore PostgreSQL dump\n'
          '- [ ] Restore SCIPIONHOME\n'
          '- [ ] Validate .env\n'
          '- [ ] Confirm SECRETKEY matches expected deployment\n'
          '- [ ] Fix permissions/ownership\n'
          '- [ ] Start services\n'
          '- [ ] Verify /health\n'
          '- [ ] Verify frontend access\n'
          '- [ ] Inspect app.log / celery.log',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#disaster-recovery-checklist'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Production Notes',
  'text': 'Backups without verification are not backups:\n'
          'Schedule regular restore drills (staging is enough) to validate credentials, file permissions, and actual '
          'recovery time.\n'
          '\n'
          'Version discipline:\n'
          'Keep backup timestamps and version labels (API version, frontend bundle version, schema revision if '
          'relevant) to simplify rollback and incident response.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#production-notes'},
 {'area': 'operations',
  'page': 'Backup and Restore',
  'title': 'Navigation',
  'text': 'Next: Logs and PID Files →',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/backup-restore/#navigation'},
 {'area': 'operations',
  'page': 'Logs and PID Files',
  'title': 'Log Location',
  'text': 'Runtime logs are stored under:\n\ntext\nSCIPIONHOME/logs/',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/logs-and-pids/#log-location'},
 {'area': 'operations',
  'page': 'Logs and PID Files',
  'title': 'Typical Log Files',
  'text': 'text\n'
          'logs/\n'
          '├── app.log\n'
          '└── celery.log\n'
          '\n'
          'app.log\n'
          '\n'
          'Usually contains API startup messages, request handling logs, and error traces.\n'
          '\n'
          'celery.log\n'
          '\n'
          'Usually contains worker startup messages, task execution logs, failures, and retries.\n'
          '\n'
          'First place to look:\n'
          'If the UI or API appears healthy but tasks fail silently, check celery.log early.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/logs-and-pids/#typical-log-files'},
 {'area': 'operations',
  'page': 'Logs and PID Files',
  'title': 'Viewing Logs',
  'text': 'CLI shortcut\n'
          '\n'
          './scripts/scipionapi logs\n'
          '\n'
          'Manual live tail\n'
          '\n'
          'tail -f scipionhome/logs/app.log\n'
          'tail -f scipionhome/logs/celery.log',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/logs-and-pids/#viewing-logs'},
 {'area': 'operations',
  'page': 'Logs and PID Files',
  'title': 'PID Files',
  'text': 'When using CLI runtime commands (start, stop, restart), ScipionAPI writes PID files under:\n'
          '\n'
          'text\n'
          '.run/\n'
          '\n'
          'Typical layout:\n'
          '\n'
          'text\n'
          '.run/\n'
          '├── api.pid\n'
          '└── worker.pid\n'
          '\n'
          'PID files help stop, restart, and inspect runtime services safely.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/logs-and-pids/#pid-files'},
 {'area': 'operations',
  'page': 'Logs and PID Files',
  'title': 'Common pitfall: stale PID files',
  'text': 'After an unexpected crash, PID files may remain even though the processes are gone.\n'
          '\n'
          'Typical symptoms:\n'
          '\n'
          '- status reports a process that is not really alive\n'
          '- start refuses to launch because a PID file already exists\n'
          '- stop cannot act on the recorded PID\n'
          '\n'
          'Always verify the process state before assuming the PID file is trustworthy.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/logs-and-pids/#common-pitfall-stale-pid-files'},
 {'area': 'operations',
  'page': 'Logs and PID Files',
  'title': 'How to use logs well',
  'text': 'A useful operational habit is to correlate three things together:\n'
          '\n'
          '1. the user action or failing workflow\n'
          '2. the API log around that time\n'
          '3. the worker log around that same time\n'
          '\n'
          'This usually helps you decide whether the failure belongs to request handling, background execution, or '
          'environment state.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/logs-and-pids/#how-to-use-logs-well'},
 {'area': 'operations',
  'page': 'Logs and PID Files',
  'title': 'Quick Ops Checklist',
  'text': '- [ ] SCIPIONHOME/logs/ exists and is writable\n'
          '- [ ] app.log updates during API requests\n'
          '- [ ] celery.log updates during task execution\n'
          '- [ ] .run/ PID files match live processes\n'
          '- [ ] logs are reviewed regularly in production',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/logs-and-pids/#quick-ops-checklist'},
 {'area': 'operations',
  'page': 'Logs and PID Files',
  'title': 'Current Split-Worker Logs and PIDs',
  'text': 'The current ScipionAPI runtime manages plugin and protocol workers independently. In addition to the '
          'files described above, the protocol worker has its own log and PID file.\n'
          '\n'
          'Current runtime log layout:\n'
          '\n'
          'text\n'
          'SCIPIONHOME/logs/\n'
          '├── app.log\n'
          '├── celery.log\n'
          '└── celery-protocols.log\n'
          '\n'
          '- app.log contains FastAPI/uvicorn output.\n'
          '- celery.log contains the plugin worker output.\n'
          '- celery-protocols.log contains the protocol worker output.\n'
          '\n'
          'Current CLI-managed PID layout:\n'
          '\n'
          'text\n'
          '.run/\n'
          '├── api.pid\n'
          '├── worker.pid\n'
          '└── protocol-worker.pid\n'
          '\n'
          'The files map to runtime processes as follows:\n'
          '\n'
          '| PID file | Process |\n'
          '|---|---|\n'
          '| api.pid | FastAPI / uvicorn |\n'
          '| worker.pid | Plugin Celery worker |\n'
          '| protocol-worker.pid | Protocol Celery worker |\n'
          '\n'
          'For manual log inspection, the protocol worker can be followed independently:\n'
          '\n'
          'bash\n'
          'tail -f scipionhome/logs/celery-protocols.log\n'
          '\n'
          'This separation is useful when API requests work correctly but only plugin tasks or protocol executions '
          'are failing.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/logs-and-pids/#current-split-worker-logs-and-pids'},
 {'area': 'operations',
  'page': 'Logs and PID Files',
  'title': 'Compute nodes',
  'text': 'On a compute node of a multi-node installation, the installation folder is shared, so each node keeps its '
          'files apart:\n'
          '\n'
          'text\n'
          '.run/nodes/ /protocol-worker.pid\n'
          'SCIPIONHOME/logs/nodes/ /celery-protocols.log\n'
          '\n'
          "is the machine's short host name. Run scipionapi logs and scipionapi status on the node to see its own.",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/logs-and-pids/#compute-nodes'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': 'Security Priorities (At a Glance)',
  'text': '- Use HTTPS\n'
          '- Protect SECRETKEY\n'
          '- Restrict CORS\n'
          '- Keep PostgreSQL and Valkey non-public\n'
          '- Enforce proper file permissions\n'
          '- Monitor logs and automate backups',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#security-priorities-at-a-glance'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '1. Use HTTPS',
  'text': 'Never expose the API over plain HTTP in production.\n'
          '\n'
          'Recommended setup:\n'
          '\n'
          '- Reverse proxy (for example nginx)\n'
          "- TLS certificates (Let's Encrypt or enterprise CA)\n"
          '\n'
          'Example public endpoints:\n'
          '\n'
          'text\n'
          'https://yourdomain.com\n'
          'https://api.yourdomain.com\n'
          '\n'
          'Why HTTPS is mandatory:\n'
          'HTTPS protects credentials, tokens, and session traffic from interception.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#1-use-https'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '2. Protect `SECRET_KEY`',
  'text': 'SECRETKEY is used to sign JWT tokens.\n'
          '\n'
          'It:\n'
          '\n'
          '- Must remain private\n'
          '- Must not be committed to version control\n'
          '- Should be rotated if compromised\n'
          '\n'
          'Recommended practices:\n'
          '\n'
          '- Use a strong random value (32+ characters minimum)\n'
          '- Store it in .env with restricted permissions\n'
          '- Consider injecting it via systemd environment configuration for additional hardening\n'
          '\n'
          'Compromise response:\n'
          'If SECRETKEY is exposed, rotate it and assume existing tokens may be untrusted.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#2-protect-secret_key'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '3. Restrict CORS',
  'text': 'Avoid permissive production CORS policies such as:\n'
          '\n'
          'python\n'
          'alloworigins=[""]\n'
          '\n'
          'Use explicit origins instead:\n'
          '\n'
          'python\n'
          'alloworigins=["https://yourdomain.com"]\n'
          '\n'
          'If you use separate frontend/API hosts, include only the required frontend origins.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#3-restrict-cors'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '4. Database Security (PostgreSQL)',
  'text': 'Recommended controls:\n'
          '\n'
          '- Use strong passwords\n'
          '- Bind PostgreSQL to localhost when possible\n'
          '- Do not expose port 5432 publicly\n'
          '- Apply firewall rules\n'
          '- Limit remote access to trusted hosts only (if remote DB is required)\n'
          '\n'
          'Defense in depth:\n'
          'Even if PostgreSQL requires credentials, network exposure should still be minimized.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#4-database-security-postgresql'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '5. Valkey Security',
  'text': 'Recommended controls:\n'
          '\n'
          '- Bind Valkey to localhost\n'
          '- Do not expose Valkey publicly\n'
          '- Consider authentication if Valkey must be remote\n'
          '- Restrict network access with firewall rules\n'
          '\n'
          'High-risk exposure:\n'
          'Public Valkey exposure is a common operational mistake and can lead to severe compromise.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#5-valkey-security'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '6. Firewall Configuration',
  'text': 'Typical port policy:\n'
          '\n'
          '- 80 / 443 → public (if internet-facing)\n'
          '- 8080 → internal only (when reverse proxy is used)\n'
          '- 5432 (PostgreSQL) → not public\n'
          '- 6379 (Valkey) → not public\n'
          '\n'
          'Use host firewall rules and/or cloud security groups to enforce this.\n'
          '\n'
          'Several machines:\n'
          'With compute nodes, ports 5432 and 6379 must reach them, and only them. scipionapi multinode enable '
          '--network  :\n'
          '\n'
          "- lets PostgreSQL accept only ScipionWeb's user and database, only from that network;\n"
          '- gives Valkey a password;\n'
          '- opens the ports in ufw only for that network.\n'
          '\n'
          'Keep that network as small as possible and never use one reachable from outside.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#6-firewall-configuration'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '7. JWT Security Practices',
  'text': 'JWT security depends on both backend behavior and deployment choices.\n'
          '\n'
          'Recommended:\n'
          '\n'
          '- Use HTTPS everywhere\n'
          '- Use short-lived access tokens\n'
          '- Consider refresh-token strategy\n'
          '- Invalidate access when users are disabled or permissions change (application-policy dependent)',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#7-jwt-security-practices'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '8. File Permissions',
  'text': 'Protect runtime configuration and data:\n'
          '\n'
          '- .env should be readable only by the service user\n'
          '- scipionhome should not be world-writable\n'
          '- Ensure correct ownership for the runtime user/service\n'
          '\n'
          'Example:\n'
          '\n'
          'chmod 600 scipionhome/.env\n'
          'chmod -R 750 scipionhome\n'
          '\n'
          'Optional ownership fix:\n'
          '\n'
          'chown -R youruser:yourgroup scipionhome',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#8-file-permissions'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '9. Production Hardening Checklist',
  'text': '- [ ] HTTPS enabled\n'
          '- [ ] Reverse proxy configured\n'
          '- [ ] SECRETKEY secured\n'
          '- [ ] CORS restricted to trusted origins\n'
          '- [ ] PostgreSQL not publicly exposed\n'
          '- [ ] Valkey not publicly exposed\n'
          '- [ ] Runtime permissions hardened (.env, SCIPIONHOME)\n'
          '- [ ] Logs monitored\n'
          '- [ ] Backups automated and tested',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#9-production-hardening-checklist'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': '10. Security Model Summary',
  'text': 'ScipionWeb security relies on:\n'
          '\n'
          '- JWT authentication\n'
          '- Backend validation\n'
          '- Secure runtime configuration\n'
          '- Deployment hardening (network, proxy, permissions, monitoring)\n'
          '\n'
          'Operational reality:\n'
          'Security is not a one-time setup. Revisit your configuration after upgrades, topology changes, or new '
          'public exposure.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#10-security-model-summary'},
 {'area': 'operations',
  'page': 'Security Notes',
  'title': 'Navigation',
  'text': '← Previous: Logs and PID Files',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/operations/security/#navigation'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'What `bootstrap` does *not* do',
  'text': '- It does not create the database\n'
          '- It does not run Alembic migrations\n'
          '- It does not start services\n'
          '\n'
          'Scope:\n'
          'bootstrap focuses only on preparing the Python execution environment.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#what-bootstrap-does-not-do'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'Usage',
  'text': './scripts/scipionapi bootstrap',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#usage'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'What It Does',
  'text': 'When executed, bootstrap typically:\n'
          '\n'
          '1. Checks whether Conda is available\n'
          '2. Creates the environment (default: scipion4Web) if it does not exist\n'
          '3. Installs the Python version (default: 3.11; choose another with --python or SCIPIONAPIPYTHONVERSION; '
          'an existing environment keeps its own)\n'
          '4. Upgrades pip\n'
          '5. Installs dependencies from requirements.txt\n'
          '6. Installs the package in editable mode (pip install -e .)',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#what-it-does'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'Default Environment Name',
  'text': 'Default Conda environment name:\n'
          '\n'
          'text\n'
          'scipion4Web\n'
          '\n'
          'This may be overridden in advanced setups (wrapper/env config, depending on version/workflow).',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#default-environment-name'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'When to Use `bootstrap`',
  'text': 'Use bootstrap when you need to:\n'
          '\n'
          '- Prepare a development environment\n'
          '- Debug Conda or dependency issues\n'
          '- Rebuild or refresh the Python runtime\n'
          '- Perform a manual installation flow before install\n'
          '\n'
          'Manual / advanced flow\n'
          '\n'
          './scripts/scipionapi bootstrap\n'
          './scripts/scipionapi install --user "admin" --email "admin@example.com"\n'
          './scripts/scipionapi start\n'
          '\n'
          'One-shot alternative\n'
          '\n'
          './scripts/scipionapi provision --user "admin" --email "admin@example.com"',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#when-to-use-bootstrap'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'Idempotent Behavior',
  'text': 'Running bootstrap multiple times is generally safe.\n'
          '\n'
          'Typical behavior:\n'
          '\n'
          '- Does not recreate the environment if it already exists\n'
          '- Reinstalls or refreshes dependencies if needed',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#idempotent-behavior'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'Example',
  'text': './scripts/scipionapi bootstrap\n\nAfter completion:\n\nconda activate scipion4Web\nscipionapi --help',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#example'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'Troubleshooting',
  'text': 'Conda not found:\n'
          'Confirm Conda is installed and available in PATH:\n'
          '\n'
          'conda --version\n'
          '\n'
          'Environment created but command still fails:\n'
          'Activate the environment manually and test:\n'
          '\n'
          'conda activate scipion4Web\n'
          'scipionapi --help\n'
          '\n'
          'Dependency installation errors:\n'
          'Re-run bootstrap and inspect terminal output. If the problem persists, verify Conda/Python compatibility '
          'and network access for package downloads.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#troubleshooting'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'Next Step',
  'text': 'After bootstrap, continue with:\n'
          '\n'
          './scripts/scipionapi install --user "admin" --email "admin@example.com"\n'
          '\n'
          'Or use the one-shot alternative:\n'
          '\n'
          './scripts/scipionapi provision --user "admin" --email "admin@example.com"',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#next-step'},
 {'area': 'cli',
  'page': '`bootstrap` Command',
  'title': 'Navigation',
  'text': '← Previous: CLI Reference Overview\n\nNext: install →',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/bootstrap/#navigation'},
 {'area': 'cli',
  'page': '`doctor` Command',
  'title': 'Usage',
  'text': 'Run the default full diagnostics:\n'
          '\n'
          './scripts/scipionapi doctor\n'
          '\n'
          'Run a faster check that skips heavier operations such as importing the FastAPI app and checking Alembic '
          'state:\n'
          '\n'
          './scripts/scipionapi doctor --quick\n'
          '\n'
          'Run in strict mode, which exits with code 1 when failures are detected:\n'
          '\n'
          './scripts/scipionapi doctor --strict\n'
          '\n'
          'You can combine both options:\n'
          '\n'
          './scripts/scipionapi doctor --quick --strict',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/doctor/#usage'},
 {'area': 'cli',
  'page': '`doctor` Command',
  'title': 'What It Checks',
  'text': 'doctor currently validates:\n'
          '\n'
          '- repository markers such as pyproject.toml, alembic.ini, and the app/ package\n'
          '- Python version used by the CLI\n'
          '- Conda executable resolution\n'
          '- target Conda environment visibility\n'
          '- active Conda environment\n'
          '- .env presence and required variables\n'
          '- SCIPIONHOME, logs, projects, and Scipion config files\n'
          '- availability of commands such as alembic, psql, and valkey-server\n'
          '- imports for key Python dependencies\n'
          '- PostgreSQL connectivity using DATABASEURL\n'
          '- Valkey broker TCP connectivity using BROKERURL\n'
          '- API TCP reachability\n'
          '- API and worker PID files\n'
          '- integrated Web bundle layout when SERVEWEB=1\n'
          '- Alembic current revision in full mode\n'
          '- multi-node deployment readiness (see below)',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/doctor/#what-it-checks'},
 {'area': 'cli',
  'page': '`doctor` Command',
  'title': 'Multi-Node Deployment Checks',
  'text': 'doctor also validates configuration that only matters once more than one node participates in the same '
          'deployment (see Multi-Node Cluster Deployment).\n'
          '\n'
          'By default, doctor assumes a single-node deployment and only warns about the conditions below, so an '
          'ordinary local installation never fails these checks. Opt into strict multi-node validation with:\n'
          '\n'
          'bash\n'
          'SCIPIONAPIDEPLOYMENTMODE=multi-node ./scripts/scipionapi doctor --strict\n'
          '\n'
          'With SCIPIONAPIDEPLOYMENTMODE=multi-node, three checks escalate from WARN to FAIL:\n'
          '\n'
          '| Check | What it verifies | Fails when (multi-node mode) |\n'
          '|---|---|---|\n'
          '| Broker reachability | BROKERURL does not resolve to localhost/127.0.0.1 | The broker host is a loopback '
          'address — unreachable from any other node |\n'
          '| Database reachability | DATABASEURL does not resolve to localhost/127.0.0.1 | The database host is a '
          'loopback address — unreachable from any other node |\n'
          '| Projects filesystem | PROJECTSPATH is mounted from a filesystem type that looks shared (nfs, nfs4, '
          'cifs, glusterfs, ceph, ...) rather than local-only (ext4, xfs, btrfs, tmpfs, ...) | The filesystem type '
          'looks local-only, meaning other nodes would not see the same project/run files |\n'
          '\n'
          'A fourth informational row, Deployment mode, always reports whether SCIPIONAPIDEPLOYMENTMODE is '
          'single-node (default) or multi-node.\n'
          '\n'
          'Run this on every node:\n'
          'Run SCIPIONAPIDEPLOYMENTMODE=multi-node ./scripts/scipionapi doctor --strict on the master and on every '
          'worker node before starting services. It is the fastest way to catch a worker that would otherwise start, '
          'look healthy in its own log, and never actually receive any work because it is still pointed at its own '
          'localhost broker/database.\n'
          '\n'
          'Unset SCIPIONAPIDEPLOYMENTMODE is safe:\n'
          'Leaving the variable unset (or set to single-node) preserves the original behavior exactly: loopback '
          'broker/database URLs and a local filesystem for PROJECTSPATH remain informational WARNs, never FAILs.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/doctor/#multi-node-deployment-checks'},
 {'area': 'cli',
  'page': '`doctor` Command',
  'title': 'When to Use It',
  'text': 'Run doctor after installation:\n'
          '\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.com"\n'
          '\n'
          './scripts/scipionapi doctor\n'
          '\n'
          'Run it after starting services:\n'
          '\n'
          './scripts/scipionapi start\n'
          './scripts/scipionapi doctor --quick\n'
          '\n'
          'Run it in automation or installer tests:\n'
          '\n'
          './scripts/scipionapi doctor --quick --strict',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/doctor/#when-to-use-it'},
 {'area': 'cli',
  'page': '`doctor` Command',
  'title': 'Understanding Results',
  'text': '| Status | Meaning |\n'
          '|---|---|\n'
          '| OK | The check passed |\n'
          '| WARN | The check is not necessarily fatal, but should be reviewed |\n'
          '| FAIL | The check failed and should be fixed |\n'
          '\n'
          'A common pre-install result is a warning about the missing .env file. That is expected before running '
          'install or provision.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/doctor/#understanding-results'},
 {'area': 'cli',
  'page': '`doctor` Command',
  'title': 'Typical Issues Revealed by `doctor`',
  'text': 'Wrong Conda environment:\n'
          'If the active environment differs from the expected one, run commands through ./scripts/scipionapi or '
          'export SCIPIONAPICONDAENV explicitly.\n'
          '\n'
          'PostgreSQL is unreachable:\n'
          'Check DATABASEURL, local PostgreSQL service status, role permissions, and whether the target database '
          'exists.\n'
          '\n'
          'Valkey is unreachable:\n'
          'Start Valkey or update BROKERURL to point to the correct broker.\n'
          '\n'
          'API TCP check failed:\n'
          'The services may not be running yet. Try ./scripts/scipionapi start and then run doctor again.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/doctor/#typical-issues-revealed-by-doctor'},
 {'area': 'cli',
  'page': '`doctor` Command',
  'title': 'Navigation',
  'text': '← Previous: provision\n\nNext: runtime commands →',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/doctor/#navigation'},
 {'area': 'cli',
  'page': '`install` Command',
  'title': 'Usage',
  'text': 'Interactive password prompt:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi install \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org"\n'
          '\n'
          'Automated form:\n'
          '\n'
          'bash\n'
          "export SCIPIONAPIADMINPASSWORD=' '\n"
          '\n'
          './scripts/scipionapi install \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org" \\\n'
          '--password-env SCIPIONAPIADMINPASSWORD\n'
          '\n'
          'Password safety:\n'
          '--pass and --password remain available for compatibility, but hidden input or --password-env is '
          'preferred.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/install/#usage'},
 {'area': 'cli',
  'page': '`install` Command',
  'title': 'Mental model',
  'text': 'Use install when:\n'
          '\n'
          '- the Conda/Python environment is already prepared\n'
          '- you want to inspect configuration/database setup separately from startup\n'
          '- you are debugging the lower-level provisioning sequence\n'
          '\n'
          'Typical advanced sequence:\n'
          '\n'
          'text\n'
          'bootstrap → install → doctor → start\n'
          '\n'
          'provision combines those layers for convenience, and the guided install.sh adds host/release/download '
          'handling above provision.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/install/#mental-model'},
 {'area': 'cli',
  'page': '`install` Command',
  'title': 'What it does',
  'text': 'install typically:\n'
          '\n'
          '1. resolves/creates SCIPIONHOME\n'
          '2. creates or updates SCIPIONHOME/.env\n'
          '3. creates runtime directories such as logs/projects\n'
          '4. resolves the API/Web port\n'
          '5. prepares the PostgreSQL role/database in supported local setups\n'
          '6. applies Alembic migrations\n'
          '7. creates or updates the administrator account\n'
          '\n'
          'The administrator password is used for bootstrap/update of the account; it should not be treated as a '
          'persistent plaintext runtime setting.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/install/#what-it-does'},
 {'area': 'cli',
  'page': '`install` Command',
  'title': 'Port behavior',
  'text': 'Use --api-port when you need a specific fixed port:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi install \\\n'
          '--user admin \\\n'
          '--email admin@example.org \\\n'
          '--api-port 39080\n'
          '\n'
          'If --api-port is omitted:\n'
          '\n'
          '- an existing APIPORT is preserved when appropriate\n'
          '- otherwise a free port is selected automatically\n'
          '- the resolved port is persisted in .env\n'
          '\n'
          'Inspect it with:\n'
          '\n'
          'bash\n'
          "grep '^APIPORT=' scipionhome/.env\n"
          '\n'
          'Do not assume port 8080 for a newly configured installation.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/install/#port-behavior'},
 {'area': 'cli',
  'page': '`install` Command',
  'title': 'Database creation behavior',
  'text': 'Automatic local bootstrap\n'
          '\n'
          'For a local PostgreSQL deployment with the supported administrative access, the installer can '
          'create/ensure the configured role and database automatically.\n'
          '\n'
          'Remote/custom PostgreSQL\n'
          '\n'
          'For remote or custom PostgreSQL:\n'
          '\n'
          '- prepare the database/role through the appropriate administrative process\n'
          '- provide consistent connection settings\n'
          '- verify connectivity before applying installation/migrations\n'
          '\n'
          'Use the manual installation/configuration guidance for these advanced topologies.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/install/#database-creation-behavior'},
 {'area': 'cli',
  'page': '`install` Command',
  'title': 'What to do next',
  'text': 'bash\n'
          './scripts/scipionapi doctor\n'
          './scripts/scipionapi start\n'
          './scripts/scipionapi status\n'
          '\n'
          'Then resolve the actual port:\n'
          '\n'
          'bash\n'
          'APIPORT="$(grep \'^APIPORT=\' scipionhome/.env | tail -n 1 | cut -d= -f2-)"\n'
          'curl "http://localhost:${APIPORT}/health"',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/install/#what-to-do-next'},
 {'area': 'cli',
  'page': '`install` Command',
  'title': 'Re-running `install`',
  'text': 'Common installation operations are designed to be reusable:\n'
          '\n'
          '- existing database data is not blindly dropped\n'
          '- migrations are applied as needed\n'
          '- administrator credentials can be updated\n'
          '- existing API port is preserved unless intentionally changed\n'
          '\n'
          'For an installed packaged release that needs a newer version, use update rather than treating the change '
          'as a fresh install.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/install/#re-running-install'},
 {'area': 'cli',
  'page': '`install` Command',
  'title': 'Common issues',
  'text': 'PostgreSQL authentication failed:\n'
          'Verify the configured database endpoint/credentials and the actual PostgreSQL role.\n'
          '\n'
          'Alembic migration error:\n'
          'Inspect database connectivity and migration state before retrying.\n'
          '\n'
          'Port expectation mismatch:\n'
          'Read APIPORT from .env; automatic port selection is supported.\n'
          '\n'
          'Environment looks inconsistent:\n'
          'Run ./scripts/scipionapi doctor to inspect Conda, .env, PostgreSQL, Valkey, imports, and runtime state.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/install/#common-issues'},
 {'area': 'cli',
  'page': 'Several Machines (`multinode`, `node`)',
  'title': '`multinode enable`',
  'text': 'bash\n'
          './scripts/scipionapi multinode enable --network 10.0.0.0/24 [--host NAME] [--dry-run] [--yes]\n'
          '\n'
          '| Option | Meaning |\n'
          '|---|---|\n'
          "| --network CIDR | Required. The nodes' network; only it gets in. 0.0.0.0/0 is refused |\n"
          '| --host NAME | The name the nodes reach this machine by (default: its full host name) |\n'
          '| --dry-run | Print the plan and change nothing |\n'
          '| --yes, -y | Do not ask for confirmation |\n'
          '\n'
          'Steps, in order:\n'
          '\n'
          '1. PostgreSQL, when it runs on this machine:\n'
          "- listenaddresses = '', set with ALTER SYSTEM;\n"
          "- one line in pghba.conf for ScipionWeb's user and database from the network, marked # ScipionWeb "
          "multi-node, with the server's own password method (scram-sha-256 or md5);\n"
          '- a restart.\n'
          '2. Valkey, when it runs on this machine:\n'
          '- bind 0.0.0.0 -::1 and a requirepass in its configuration file (the old bind and requirepass lines are '
          'commented out);\n'
          '- a restart. An existing password is kept.\n'
          '3. Firewall: if ufw is active, ports 5432 and 6379 are opened to the network.\n'
          '4. .env:\n'
          '- POSTGRESHOST, DATABASEURL, BROKERURL and RESULTBACKENDURL use the host name instead of localhost, and '
          'the Valkey URLs carry its password;\n'
          '- it adds SCIPIONAPIDEPLOYMENTMODE=multi-node, SCIPIONAPIMAINNODE and SCIPIONAPIMULTINODENETWORK.\n'
          '5. Restart of the API and the workers of this machine.\n'
          '\n'
          'After them, it checks that the database and Valkey answer on the host name.\n'
          '\n'
          'When the database or Valkey runs on another machine, the plan says so and leaves it alone: open it to the '
          'network yourself.\n'
          '\n'
          'The changed files are copied first to scipionhome/multinode/backup- - /.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/multinode/#multinode-enable'},
 {'area': 'cli',
  'page': 'Several Machines (`multinode`, `node`)',
  'title': '`multinode compute`',
  'text': 'bash\n'
          './scripts/scipionapi multinode compute off [--force]\n'
          './scripts/scipionapi multinode compute on\n'
          '\n'
          "off stops the main node's protocol worker and writes SCIPIONAPIMAINRUNSPROTOCOLS=0 to the .env. After "
          'it:\n'
          '\n'
          '- start, restart and update start the API and the plugin worker only;\n'
          "- start --role protocols, and the web's protocol-worker buttons, are refused with a message.\n"
          '\n'
          'It refuses while protocols run on the main node, unless --force is given (they are killed). It warns when '
          'no compute node answers.\n'
          '\n'
          'on writes 1 and starts the worker again.\n'
          '\n'
          'Not when protocols go to SLURM:\n'
          "The main node's protocol worker is the one that submits SLURM jobs (sbatch) and follows them. Turn it off "
          'only when every protocol runs on compute nodes joined with node join.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/multinode/#multinode-compute'},
 {'area': 'cli',
  'page': 'Several Machines (`multinode`, `node`)',
  'title': '`node join`',
  'text': 'bash\n'
          './scripts/scipionapi node join [--queue NAME] [--concurrency N] [--host NAME]\n'
          'or, from the installer:\n'
          './install.sh --join /path/to/installation [--queue NAME] [--concurrency N] [--host NAME]\n'
          '\n'
          '| Option | Meaning | Default |\n'
          '|---|---|---|\n'
          '| --queue NAME | The Celery queue the node takes protocols from | protocols |\n'
          '| --concurrency N | Protocols at a time | 12 |\n'
          '| --host NAME | With --queue: make the Scipion host NAME (a copy of localhost if it does not exist) and '
          'send its protocols to this queue | — |\n'
          '\n'
          'Checks, all from this machine:\n'
          '\n'
          '- the installation is multi-node (multinode enable was run), and this is not the main node;\n'
          '- the installation folder, SCIPIONHOME and PROJECTSPATH are there and writable;\n'
          '- SCIPIONHOME belongs to this user (same uid);\n'
          "- the main node's database and Valkey answer;\n"
          '- the GPUs (nvidia-smi), for information.\n'
          '\n'
          'If any of them fails, nothing is written. Otherwise:\n'
          '\n'
          "1. It writes the node's profile scipionhome/nodes/ .env:\n"
          '\n'
          'text\n'
          'SCIPIONAPINODEROLE=protocols\n'
          'PROTOCOLSCELERYQUEUE=protocols-gpu\n'
          'PROTOCOLWORKERCONCURRENCY=12\n'
          'LOGSPATH=/home/scipion/scipionweb/scipionhome/logs/nodes/gpu-01\n'
          '\n'
          '2. With --host, it updates scipionhome/config/hosts.conf and scipionhome/config/celeryqueuerouting.json.\n'
          '3. It starts the protocol worker and waits until it answers.\n'
          '\n'
          "The node's name is its short host name (gpu-01.cnb.csic.es → gpu-01).",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/multinode/#node-join'},
 {'area': 'cli',
  'page': 'Several Machines (`multinode`, `node`)',
  'title': '`node leave`',
  'text': 'bash\n'
          './scripts/scipionapi node leave\n'
          '\n'
          "Stops the node's worker and removes its profile. Its logs stay in scipionhome/logs/nodes/ /. The queue "
          'routes it made with --host stay too, as other nodes may use them.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/multinode/#node-leave'},
 {'area': 'cli',
  'page': 'Several Machines (`multinode`, `node`)',
  'title': '`node list`',
  'text': 'bash\n'
          './scripts/scipionapi node list\n'
          '\n'
          'Shows the main node, every compute node with its queue and concurrency, whether its worker answers now, '
          "and any other worker answering (the main node's).",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/multinode/#node-list'},
 {'area': 'cli',
  'page': 'Several Machines (`multinode`, `node`)',
  'title': 'How the other commands behave on a node',
  'text': 'On a machine with a node profile:\n'
          '\n'
          "- start, stop, restart, status and logs without --role act on the node's protocol worker only. The API "
          'and the plugin worker never start on a node.\n'
          "- PID files go to .run/nodes/ /, so they never mix with the main node's.\n"
          '- Logs go to scipionhome/logs/nodes/ /.\n'
          "- doctor reads the node's profile and checks the node.",
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/multinode/#how-the-other-commands-behave-on-a-node'},
 {'area': 'cli',
  'page': '`provision` Command',
  'title': 'API-only usage',
  'text': 'bash\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org"\n'
          '\n'
          'The CLI asks for the admin password using hidden input.\n'
          '\n'
          'For automation:\n'
          '\n'
          'bash\n'
          "export SCIPIONAPIADMINPASSWORD=' '\n"
          '\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org" \\\n'
          '--password-env SCIPIONAPIADMINPASSWORD',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/provision/#api-only-usage'},
 {'area': 'cli',
  'page': '`provision` Command',
  'title': 'Integrated API + Web usage',
  'text': 'bash\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org" \\\n'
          '--web-dist /path/to/ScipionWeb-vX.Y.Z-dist.zip\n'
          '\n'
          'Automated form:\n'
          '\n'
          'bash\n'
          "export SCIPIONAPIADMINPASSWORD=' '\n"
          '\n'
          './scripts/scipionapi provision \\\n'
          '--user "admin" \\\n'
          '--email "admin@example.org" \\\n'
          '--password-env SCIPIONAPIADMINPASSWORD \\\n'
          '--web-dist /path/to/ScipionWeb-vX.Y.Z-dist.zip\n'
          '\n'
          'Password safety:\n'
          '--pass and --password are supported for compatibility, but hidden prompts or --password-env are preferred '
          'because command-line values can be exposed in shell history/process listings.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/provision/#integrated-api-web-usage'},
 {'area': 'cli',
  'page': '`provision` Command',
  'title': 'Important options',
  'text': '| Option | Description |\n'
          '|---|---|\n'
          '| --user | Admin username |\n'
          '| --email | Admin email |\n'
          '| --password-env | Name of an environment variable containing the admin password |\n'
          '| --pass, --password | Direct password argument; supported but not recommended |\n'
          '| --web-dist | Vite dist directory or ZIP containing the compiled frontend |\n'
          '| --api-mount-path | API mount path in integrated mode (default /api) |\n'
          '| --api-base-url | API base URL written for the frontend |\n'
          '| --api-port | Fixed API/Web port; if omitted, preserve existing APIPORT or select a free port |\n'
          '| --bootstrap, --no-bootstrap | Enable/skip bootstrap phase |\n'
          '| --env-name | Conda environment name |\n'
          '| --python | Python version for the Conda environment |\n'
          '| --install-scipion-core, --no-install-scipion-core | Control automatic Scipion core installation |\n'
          '| --scipion-core-packages | Space-separated Scipion core package list |\n'
          '\n'
          'Use ./scripts/scipionapi provision --help for the current complete option list.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/provision/#important-options'},
 {'area': 'cli',
  'page': '`provision` Command',
  'title': 'What it does',
  'text': 'A normal integrated run performs:\n'
          '\n'
          '1. Conda bootstrap when enabled\n'
          '2. Python dependency setup\n'
          '3. Scipion core dependency setup when required\n'
          '4. SCIPIONHOME creation/update\n'
          '5. .env generation/update\n'
          '6. API/Web port resolution\n'
          '7. PostgreSQL role/database bootstrap in supported local setups\n'
          '8. Alembic migrations\n'
          '9. admin-user creation/update\n'
          '10. Web bundle deployment\n'
          '11. API and Celery startup',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/provision/#what-it-does'},
 {'area': 'cli',
  'page': '`provision` Command',
  'title': 'Port selection',
  'text': 'The runtime is not tied to port 8080.\n'
          '\n'
          'If --api-port is omitted, provisioning:\n'
          '\n'
          '- preserves an existing configured APIPORT when appropriate, or\n'
          '- selects a free port automatically\n'
          '\n'
          'and persists the value in SCIPIONHOME/.env.\n'
          '\n'
          'To choose a fixed port:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi provision \\\n'
          '--user admin \\\n'
          '--email admin@example.org \\\n'
          '--web-dist /path/to/ScipionWeb-vX.Y.Z-dist.zip \\\n'
          '--api-port 39080',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/provision/#port-selection'},
 {'area': 'cli',
  'page': '`provision` Command',
  'title': 'Resulting URLs',
  'text': 'Read the actual port after provisioning:\n'
          '\n'
          'bash\n'
          'APIPORT="$(grep \'^APIPORT=\' scipionhome/.env | tail -n 1 | cut -d= -f2-)"\n'
          'echo "$APIPORT"\n'
          '\n'
          'API-only mode\n'
          '\n'
          'text\n'
          'http://localhost: /docs\n'
          '\n'
          'Integrated mode\n'
          '\n'
          'text\n'
          'http://localhost: /\n'
          'http://localhost: /api/docs',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/provision/#resulting-urls'},
 {'area': 'cli',
  'page': '`provision` Command',
  'title': 'Verification',
  'text': 'bash\n'
          './scripts/scipionapi status\n'
          './scripts/scipionapi doctor --quick\n'
          '\n'
          'APIPORT="$(grep \'^APIPORT=\' scipionhome/.env | tail -n 1 | cut -d= -f2-)"\n'
          'curl "http://localhost:${APIPORT}/health"\n'
          '\n'
          'For deeper diagnostics:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi doctor\n'
          './scripts/scipionapi logs',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/provision/#verification'},
 {'area': 'cli',
  'page': '`provision` Command',
  'title': 'Re-running `provision`',
  'text': 'Common provisioning operations are designed to be reusable:\n'
          '\n'
          '- existing Conda environment can be reused\n'
          '- database state is not blindly destroyed\n'
          '- migrations are reapplied as needed\n'
          '- admin credentials can be updated\n'
          '- Web assets can be redeployed\n'
          '- existing port configuration is preserved unless changed intentionally\n'
          '\n'
          'For a normal version upgrade of an existing packaged installation, use update instead.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/provision/#re-running-provision'},
 {'area': 'cli',
  'page': '`provision` Command',
  'title': 'When to use `provision` directly',
  'text': 'Use it when:\n'
          '\n'
          '- validating release ZIPs\n'
          '- using a manual download workflow\n'
          '- deploying API-only\n'
          '- hosting the frontend separately\n'
          '- customizing mount/base URLs\n'
          '- debugging installation layers\n'
          '- writing infrastructure automation\n'
          '\n'
          'For ordinary new installations, start with install.sh.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/provision/#when-to-use-provision-directly'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Default release build',
  'text': 'From the ScipionAPI repository, with ScipionWeb available as a sibling repository, run:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi release \\\n'
          '--downloads-dir /path/to/release/files\n'
          '\n'
          'By default the command:\n'
          '\n'
          '1. reads the ScipionAPI version from the CLI package\n'
          '2. reads the ScipionWeb version from package.json\n'
          '3. refuses to continue unless both versions match\n'
          '4. runs npm run build:web in ScipionWeb\n'
          '5. builds the API archive from the managed ScipionAPI release paths\n'
          '6. packages the compiled Web distribution\n'
          '7. creates the paired release ZIP files in --downloads-dir\n'
          '\n'
          'For version 4.0.1, the default artifacts are:\n'
          '\n'
          'text\n'
          'ScipionAPI-v4.0.1.zip\n'
          'ScipionWeb-v4.0.1-dist.zip\n'
          '\n'
          'ScipionWeb is resolved by default as a sibling directory named ScipionWeb. Use --web-root '
          '/path/to/ScipionWeb or SCIPIONWEBRELEASEWEBROOT when it lives elsewhere.\n'
          '\n'
          '--version is an assertion:\n'
          'The release version normally comes from ScipionAPI and ScipionWeb themselves. Passing --version vX.Y.Z '
          'asks the command to verify that both packages already declare that version; it does not override them.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#default-release-build'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Build and publish in one command',
  'text': 'To build fresh artifacts and then publish them:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi release \\\n'
          '--upload \\\n'
          '--downloads-dir /path/to/release/files\n'
          '\n'
          'install.sh is taken automatically from the current ScipionAPI repository root. You do not need to copy it '
          'into the release directory.\n'
          '\n'
          'Upload existing archives without rebuilding\n'
          '\n'
          'The previous publication workflow is still available explicitly:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi release \\\n'
          '--upload \\\n'
          '--no-build \\\n'
          '--version v4.0.1 \\\n'
          '--downloads-dir /path/to/release/files\n'
          '\n'
          'With --no-build, the paired ZIP files must already exist. --no-build is only valid together with '
          '--upload.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#build-and-publish-in-one-command'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Always run a dry run first',
  'text': 'bash\n'
          './scripts/scipionapi release \\\n'
          '--upload \\\n'
          '--version v4.0.1 \\\n'
          '--downloads-dir /path/to/release/files \\\n'
          '--dry-run\n'
          '\n'
          'A release dry run is read-only with respect to the remote server, but it is not purely local. With the '
          'default build behavior it does create fresh local release ZIPs first, then deliberately:\n'
          '\n'
          '- validates the paired ScipionAPI/ScipionWeb versions\n'
          '- builds the Web distribution and local release files\n'
          '- connects to the configured release server over SSH\n'
          '- validates the remote release directory\n'
          '- downloads the current remote manifest.json when present\n'
          '- checks whether the version or target ZIP filenames already exist remotely\n'
          '- calculates the release metadata and SHA256 values\n'
          '- prints the resolved publication plan\n'
          '\n'
          'It does not upload or replace remote files.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#always-run-a-dry-run-first'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Official defaults',
  'text': 'The current ScipionWeb release publisher defaults to:\n'
          '\n'
          'text\n'
          'SSH login:\n'
          'scipion@nolan.cnb.csic.es\n'
          '\n'
          'Remote directory:\n'
          '/home/scipion/scipionfiles/downloads/scipion/scipionWeb\n'
          '\n'
          'Public URL:\n'
          'https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/\n'
          '\n'
          'These values can be overridden with:\n'
          '\n'
          'text\n'
          '--login\n'
          '--remote-dir\n'
          '--base-url\n'
          '\n'
          'or the corresponding environment variables:\n'
          '\n'
          'text\n'
          'SCIPIONWEBRELEASELOGIN\n'
          'SCIPIONWEBRELEASEREMOTEDIR\n'
          'SCIPIONWEBRELEASEBASEURL',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#official-defaults'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': '`manifest.json` is automatic',
  'text': 'You do not prepare manifest.json manually before publishing.\n'
          '\n'
          'The publisher follows this logic:\n'
          '\n'
          '1. try to download the current remote manifest.json\n'
          '2. if it exists, preserve its existing releases entries\n'
          '3. add or update the requested release entry locally\n'
          '4. calculate the API/Web SHA256 values and file sizes\n'
          '5. update latest unless --no-latest was requested\n'
          '6. publish the resulting manifest only after the release files are in place\n'
          '\n'
          'If no remote manifest.json exists, the command creates a new one containing the release being published.\n'
          '\n'
          'This means a normal release directory only needs:\n'
          '\n'
          'text\n'
          'ScipionAPI-vX.Y.Z.zip\n'
          'ScipionWeb-vX.Y.Z-dist.zip',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#manifestjson-is-automatic'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Safe publication order',
  'text': 'The remote publication order is intentionally:\n'
          '\n'
          'text\n'
          '1. ScipionAPI ZIP\n'
          '2. ScipionWeb ZIP\n'
          '3. install.sh\n'
          '4. manifest.json\n'
          '\n'
          'Each upload is staged through a temporary remote filename and moved into place atomically.\n'
          '\n'
          'Publishing manifest.json last is important: users should never see a newly advertised release until its '
          'downloadable artifacts are already available.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#safe-publication-order'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Existing versions are protected',
  'text': 'Without --force, the publisher refuses to replace a version when either:\n'
          '\n'
          '- the remote manifest already contains that version, or\n'
          '- the target release ZIP filenames already exist remotely\n'
          '\n'
          'Example refusal:\n'
          '\n'
          'text\n'
          'Release already appears to be published (...). Use --force only when intentionally replacing it.\n'
          '\n'
          'This is a safety feature, not a publication failure.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#existing-versions-are-protected'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Previewing an already-published version',
  'text': 'If you intentionally want to inspect the complete plan for an existing version without changing anything, '
          'combine --force with --dry-run:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi release \\\n'
          '--upload \\\n'
          '--version v4.0.0 \\\n'
          '--downloads-dir /path/to/release/files \\\n'
          '--force \\\n'
          '--dry-run\n'
          '\n'
          'Do not remove --dry-run casually:\n'
          '--force without --dry-run allows intentional replacement of an already-published version. Use it only '
          'when replacement is genuinely required.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#previewing-an-already-published-version'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Publishing without changing `latest`',
  'text': "By default, the new release becomes the manifest's latest version.\n"
          '\n'
          'To publish a release entry without moving latest:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi release \\\n'
          '--upload \\\n'
          '--version v4.0.1 \\\n'
          '--downloads-dir /path/to/release/files \\\n'
          '--no-latest\n'
          '\n'
          'This is useful for controlled publication or pre-release scenarios where the release should exist but '
          'should not yet become the default update target.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#publishing-without-changing-latest'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Non-interactive confirmation',
  'text': 'The command asks for confirmation before a real upload.\n'
          '\n'
          'For controlled automation:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi release \\\n'
          '--upload \\\n'
          '--version v4.0.1 \\\n'
          '--downloads-dir /path/to/release/files \\\n'
          '--yes\n'
          '\n'
          'Use --yes only in release automation where the preceding validations are already trusted.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#non-interactive-confirmation'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Custom artifact paths',
  'text': 'If the filenames do not follow the normal convention, use:\n'
          '\n'
          'text\n'
          '--api-file\n'
          '--web-file\n'
          '\n'
          'The standard naming convention is strongly preferred because the installer, updater, server directory, '
          'and documentation all become easier to reason about.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#custom-artifact-paths'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Post-publication verification',
  'text': 'After uploading the artifacts and publishing manifest.json, the command checks the public manifest URL '
          'and verifies that the published release can be observed through HTTP.\n'
          '\n'
          'A temporary visibility problem at the public endpoint is reported as a warning rather than pretending '
          'verification succeeded.\n'
          '\n'
          'For an important release, also verify manually that:\n'
          '\n'
          'text\n'
          'manifest.json\n'
          'ScipionAPI-vX.Y.Z.zip\n'
          'ScipionWeb-vX.Y.Z-dist.zip\n'
          'install.sh\n'
          '\n'
          'are reachable from the public release endpoint.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#post-publication-verification'},
 {'area': 'cli',
  'page': 'Release Builder and Publisher',
  'title': 'Recommended maintainer workflow',
  'text': 'bash\n'
          '1. Optionally build locally first and inspect the generated pair.\n'
          './scripts/scipionapi release \\\n'
          '--downloads-dir /path/to/release/files\n'
          '\n'
          '2. Rebuild and validate the real remote state and release plan.\n'
          './scripts/scipionapi release \\\n'
          '--upload \\\n'
          '--downloads-dir /path/to/release/files \\\n'
          '--dry-run\n'
          '\n'
          '3. Rebuild and publish after reviewing the plan.\n'
          './scripts/scipionapi release \\\n'
          '--upload \\\n'
          '--downloads-dir /path/to/release/files\n'
          '\n'
          'For routine releases, the source versions in ScipionAPI and ScipionWeb are the source of truth. Add '
          '--version vX.Y.Z when you want an explicit version assertion.\n'
          '\n'
          'That is the normal release path. Manual ZIP assembly and manual editing of the remote manifest should not '
          'be part of routine publication.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/release/#recommended-maintainer-workflow'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': 'Command Summary',
  'text': '| Command | Purpose |\n'
          '|---|---|\n'
          '| start | Start API and Celery |\n'
          '| stop | Stop API and Celery |\n'
          '| restart | Restart both services |\n'
          '| status | Show whether services are running |\n'
          '| logs | Tail runtime logs |',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#command-summary'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': 'Recommended mental model',
  'text': 'A practical sequence is:\n'
          '\n'
          '1. start to launch services\n'
          '2. status to confirm process state\n'
          '3. logs to verify real runtime behavior\n'
          '4. restart after configuration changes\n'
          '5. stop when shutting down intentionally\n'
          '\n'
          'status tells you whether processes exist. logs and /health tell you whether the system is actually '
          'behaving well.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#recommended-mental-model'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': '`start`',
  'text': 'Starts the API and Celery worker.\n'
          '\n'
          './scripts/scipionapi start\n'
          '\n'
          'Typical behavior:\n'
          '\n'
          '- launches API and Celery as detached processes\n'
          '- creates PID files under .run/',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#start'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': '`stop`',
  'text': 'Stops API and Celery.\n'
          '\n'
          './scripts/scipionapi stop\n'
          '\n'
          'Typical behavior:\n'
          '\n'
          '- reads PID files\n'
          '- terminates the running processes when possible',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#stop'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': '`restart`',
  'text': 'Stops and starts services again.\n'
          '\n'
          './scripts/scipionapi restart\n'
          '\n'
          'Useful after:\n'
          '\n'
          '- .env changes\n'
          '- dependency or runtime updates\n'
          '- integrated Web asset redeployments\n'
          '- transient failures',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#restart'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': '`status`',
  'text': 'Shows whether services are running.\n'
          '\n'
          './scripts/scipionapi status\n'
          '\n'
          'Process state vs health:\n'
          'status confirms process state, but not necessarily application health. Also check logs and /health.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#status'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': '`logs`',
  'text': 'Tails application logs.\n'
          '\n'
          './scripts/scipionapi logs\n'
          '\n'
          'This typically shows the API log and the worker log together.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#logs'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': '`--role` (per-node service selection)',
  'text': 'start, stop, restart, status, and logs all accept --role:\n'
          '\n'
          '| Role | Manages |\n'
          '|---|---|\n'
          '| all (default) | API + plugin worker + protocol worker — identical to pre---role behavior |\n'
          '| api | FastAPI/uvicorn only |\n'
          '| plugins | Plugin Celery worker only |\n'
          '| protocols | Protocol Celery worker only |\n'
          '\n'
          'This is the mechanism used to run only part of the stack on a given node in a Multi-Node Cluster '
          'Deployment — for example, a compute node that should run the protocol worker but never the API:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi start --role protocols\n'
          './scripts/scipionapi status --role protocols\n'
          './scripts/scipionapi stop --role protocols\n'
          '\n'
          'Default behavior is unchanged:\n'
          'Omitting --role (or passing --role all) behaves exactly as before this option existed: all three '
          'processes are managed together.\n'
          '\n'
          'An unrecognized role is rejected immediately with a clear error rather than silently falling back to all.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#role-per-node-service-selection'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': '`--queue` (custom Celery queue name)',
  'text': 'start, restart, and status also accept --queue, which overrides the Celery queue name the protocol worker '
          'listens on (default: protocols). This is normally combined with --role protocols on a dedicated node:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi start --role protocols --queue protocols-gpu\n'
          '\n'
          '--queue only affects that single invocation. To make the same queue name survive future restarts — '
          "including ones triggered from the web UI's worker restart button, which does not go through the CLI — set "
          "it in that node's .env instead:\n"
          '\n'
          'dotenv\n'
          'PROTOCOLSCELERYQUEUE=protocols-gpu\n'
          '\n'
          'A custom queue name only receives tasks once something is actually routed to it. See Multi-Node Task '
          "Routing for how scipionhome/config/celeryqueuerouting.json maps a protocol's configured Host to a Celery "
          'queue name.\n'
          '\n'
          "The worker's Celery identity does not change:\n"
          'Only the -Q   flag changes. The worker still registers as protocols@ , so remote Stop and other '
          'host-targeted operations are unaffected by a custom queue name.\n'
          '\n'
          'Compute nodes do this for you:\n'
          "On a machine that joined with node join (or install.sh --join), the node's profile sets the role, the "
          'queue and the concurrency. There, plain start, stop, restart, status and logs act on its protocol worker '
          'only, and its PID files and logs are kept apart. ➡️ Several Machines (multinode, node)',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#queue-custom-celery-queue-name'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': 'Common issues',
  'text': 'API starts but exits quickly:\n'
          'Check logs and confirm .env settings such as database, Valkey, and paths are valid.\n'
          '\n'
          'Celery not running:\n'
          'Verify Valkey availability and broker configuration.\n'
          '\n'
          'status says running but requests fail:\n'
          'Test runtime health explicitly with /health and inspect logs.\n'
          '\n'
          'No logs shown:\n'
          'Confirm the configured logs path exists and the runtime user has write permissions.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#common-issues'},
 {'area': 'cli',
  'page': 'Runtime Commands (`start`, `stop`, `restart`, `status`, `logs`)',
  'title': 'Current Runtime Worker Topology',
  'text': 'The current start, stop, restart, and status implementation manages three runtime processes:\n'
          '\n'
          'text\n'
          'ScipionAPI runtime\n'
          '├── FastAPI / uvicorn\n'
          '├── Plugin Celery worker\n'
          '└── Protocol Celery worker\n'
          '\n'
          'The two Celery workers consume different queues:\n'
          '\n'
          '| Runtime process | Queue | Concurrency |\n'
          '|---|---|---:|\n'
          '| Plugin worker | plugins | 1 |\n'
          '| Protocol worker | protocols | PROTOCOLWORKERCONCURRENCY (default 12) |\n'
          '\n'
          'When started by the CLI, the workers use the hostnames plugins@%h and protocols@%h and set '
          '--prefetch-multiplier 1.\n'
          '\n'
          'The runtime also tracks the workers independently, so status can distinguish a healthy API from a missing '
          'plugin worker or protocol worker.\n'
          '\n'
          'On a single node, all three processes normally run together (--role all, the default). On a multi-node '
          'deployment, each node manages only the subset relevant to it — for example a compute node running only '
          '--role protocols, optionally with its own --queue — while the master runs --role api and --role plugins.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/runtime/#current-runtime-worker-topology'},
 {'area': 'cli',
  'page': 'Uninstall',
  'title': 'Preview the cleanup plan',
  'text': 'bash\n'
          './scripts/scipionapi uninstall --dry-run\n'
          '\n'
          'A dry run prints what would be stopped or removed without deleting resources.\n'
          '\n'
          'For a full guided uninstall, prefer an absolute command path because the installation directory itself '
          'will disappear:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall --full --dry-run',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/uninstall/#preview-the-cleanup-plan'},
 {'area': 'cli',
  'page': 'Uninstall',
  'title': 'Regular uninstall',
  'text': 'Without --full, the repository/installation root is preserved.\n'
          '\n'
          'Available cleanup controls include:\n'
          '\n'
          'text\n'
          '--keep-database\n'
          '--keep-database-role\n'
          '--keep-web-dist\n'
          '--remove-scipion-home\n'
          '--remove-conda-env\n'
          '--keep-conda-env\n'
          '\n'
          'This mode is useful for development checkouts, troubleshooting, or selective runtime cleanup.\n'
          '\n'
          'Example: remove deployed Web assets and PostgreSQL resources while leaving the ScipionAPI checkout itself '
          'in place:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi uninstall\n'
          '\n'
          'The command asks for confirmation unless --yes/-y or --dry-run is used.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/uninstall/#regular-uninstall'},
 {'area': 'cli',
  'page': 'Uninstall',
  'title': 'Full uninstall for guided installations',
  'text': 'Installations created successfully by the public install.sh carry a marker file:\n'
          '\n'
          'text\n'
          '.scipionweb-installation\n'
          '\n'
          'That marker records the guided installation root and expected SCIPIONHOME.\n'
          '\n'
          'Preview full removal:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall --full --dry-run\n'
          '\n'
          'Then run the real removal:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall --full\n'
          '\n'
          'A full uninstall removes the installation resources, including:\n'
          '\n'
          '- running API/Celery runtime state\n'
          '- configured PostgreSQL database\n'
          '- configured PostgreSQL role when applicable\n'
          '- deployed Web assets\n'
          '- SCIPIONHOME\n'
          '- the ScipionWeb Conda environment\n'
          '- the installation root itself',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/uninstall/#full-uninstall-for-guided-installations'},
 {'area': 'cli',
  'page': 'Uninstall',
  'title': 'Full uninstall safety checks',
  'text': '--full is deliberately restrictive.\n'
          '\n'
          'Before deleting the installation root, it verifies the installation identity and refuses unsafe layouts. '
          'Guided installations are checked for:\n'
          '\n'
          '- supported marker format\n'
          '- INSTALLTYPE=guided\n'
          '- marker INSTALLROOT matching the actual installation root\n'
          '- marker SCIPIONHOME matching  /scipionhome\n'
          '- expected ScipionAPI files such as pyproject.toml, alembic.ini, and scripts/scipionapi\n'
          "- unsafe roots such as / or the user's home directory\n"
          '- symbolic-link or externally resolved SCIPIONHOME scenarios\n'
          '\n'
          'The root is validated again before the final directory removal.\n'
          '\n'
          'These checks are intentional safeguards against deleting an unrelated directory.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/uninstall/#full-uninstall-safety-checks'},
 {'area': 'cli',
  'page': 'Uninstall',
  'title': 'Why `--full` cannot keep selected resources',
  'text': 'A full uninstall represents complete removal, so it cannot be combined with:\n'
          '\n'
          'text\n'
          '--keep-database\n'
          '--keep-database-role\n'
          '--keep-web-dist\n'
          '\n'
          'If you need to preserve selected resources, use the regular uninstall mode instead.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/uninstall/#why---full-cannot-keep-selected-resources'},
 {'area': 'cli',
  'page': 'Uninstall',
  'title': 'Older packaged installations',
  'text': 'Older ZIP-based installations created before the guided installation marker existed can use:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall \\\n'
          '--full \\\n'
          '--legacy-install \\\n'
          '--dry-run\n'
          '\n'
          'If the dry-run plan is correct:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall \\\n'
          '--full \\\n'
          '--legacy-install\n'
          '\n'
          'Legacy full uninstall is accepted only when the expected packaged ScipionAPI layout can be verified.\n'
          '\n'
          'Git checkouts are not legacy packaged installs:\n'
          '--full --legacy-install explicitly refuses Git checkouts. For a development repository, use regular '
          'uninstall and remove the repository manually only if that is actually intended.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/uninstall/#older-packaged-installations'},
 {'area': 'cli',
  'page': 'Uninstall',
  'title': 'Non-interactive cleanup',
  'text': 'To skip the confirmation prompt:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi uninstall --yes\n'
          '\n'
          'For full removal:\n'
          '\n'
          'bash\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall --full --yes\n'
          '\n'
          'Use --yes only after the target and cleanup plan have already been reviewed.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/uninstall/#non-interactive-cleanup'},
 {'area': 'cli',
  'page': 'Uninstall',
  'title': 'Recommended removal workflow',
  'text': 'bash\n'
          '1. Inspect the exact plan.\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall --full --dry-run\n'
          '\n'
          '2. Review database, SCIPIONHOME, Conda env, and installation root carefully.\n'
          '\n'
          '3. Run the real uninstall only when the resolved paths are correct.\n'
          '/path/to/scipionweb/scripts/scipionapi uninstall --full\n'
          '\n'
          'For shared or important deployments, back up anything that must be retained before running full removal.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/uninstall/#recommended-removal-workflow'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Purpose',
  'text': 'update is intended for existing deployments. It preserves the runtime workspace while replacing managed '
          'application files with the selected release.\n'
          '\n'
          'It is designed to:\n'
          '\n'
          '- read the current .env\n'
          '- preserve SCIPIONHOME\n'
          '- download the matching ScipionAPI and ScipionWeb release ZIPs\n'
          '- verify checksums when available\n'
          '- create a rollback backup\n'
          '- stop services\n'
          '- update API files\n'
          '- install updated Python dependencies\n'
          '- run database migrations\n'
          '- deploy Web assets in integrated mode\n'
          '- restart services',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#purpose'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Default update',
  'text': 'Install the latest published release:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update\n'
          '\n'
          'The updater resolves latest using:\n'
          '\n'
          'text\n'
          'https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/manifest.json\n'
          '\n'
          'The manifest maps a release version to both ZIP files:\n'
          '\n'
          'text\n'
          'ScipionAPI-vX.Y.Z.zip\n'
          'ScipionWeb-vX.Y.Z-dist.zip',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#default-update'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Dry run',
  'text': 'Preview what would happen without changing files:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --dry-run\n'
          '\n'
          'Use this before updating a production or shared instance.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#dry-run'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Specific version',
  'text': 'Install a specific version:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --version v4.0.1\n'
          '\n'
          'This is useful when you want to pin the deployment to a known release instead of automatically using '
          'latest.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#specific-version'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Force reinstall',
  'text': 'If the installed version already matches the target version, use --force to reinstall it:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --version v4.0.1 --force\n'
          '\n'
          'This can be useful when validating release packages, repairing a partial update, or redeploying the Web '
          'bundle from the same release.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#force-reinstall'},
 {'area': 'cli',
  'page': 'update',
  'title': 'API-only or Web-only updates',
  'text': 'Normal releases should keep ScipionAPI and ScipionWeb aligned. For controlled maintenance or debugging, '
          'you may update only one side:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --api-only\n'
          './scripts/scipionapi update --web-only\n'
          '\n'
          'Use these options carefully. A mismatched API/Web pair may load but still behave incorrectly.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#api-only-or-web-only-updates'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Do not restart automatically',
  'text': 'To leave services stopped after the update:\n'
          '\n'
          'bash\n'
          './scripts/scipionapi update --no-restart\n'
          '\n'
          'This is useful if you want to inspect files, logs, or migrations before bringing the instance back '
          'online.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#do-not-restart-automatically'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Release source',
  'text': 'By default, updates are resolved from:\n'
          '\n'
          'text\n'
          'https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/\n'
          '\n'
          'The base URL can be configured through:\n'
          '\n'
          'env\n'
          'SCIPIONAPIUPDATEBASEURL=https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/\n'
          '\n'
          'This is useful for mirrors, staging release directories, or private deployments.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#release-source'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Manifest contract',
  'text': 'The updater expects a manifest.json similar to:\n'
          '\n'
          'json\n'
          '{\n'
          '"latest": "v4.0.1",\n'
          '"releases": {\n'
          '"v4.0.1": {\n'
          '"api": {\n'
          '"file": "ScipionAPI-v4.0.1.zip",\n'
          '"sha256": "...",\n'
          '"size": 123456\n'
          '},\n'
          '"web": {\n'
          '"file": "ScipionWeb-v4.0.1-dist.zip",\n'
          '"sha256": "...",\n'
          '"size": 123456\n'
          '}\n'
          '}\n'
          '}\n'
          '}\n'
          '\n'
          'The manifest should be cumulative. When publishing v4.0.1, keep previous releases such as v4.0.0 in the '
          'releases object.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#manifest-contract'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Generated release manifest',
  'text': 'Maintainers can generate or update the manifest with:\n'
          '\n'
          'bash\n'
          'python scripts/updatereleasemanifest.py \\\n'
          '--version v4.0.1 \\\n'
          '--downloads-dir /path/to/releases\n'
          '\n'
          'The release directory should contain:\n'
          '\n'
          'text\n'
          'manifest.json\n'
          'ScipionAPI-v4.0.1.zip\n'
          'ScipionWeb-v4.0.1-dist.zip\n'
          '\n'
          'If manifest.json already exists, the script preserves previous releases and adds or replaces the selected '
          'version.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#generated-release-manifest'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Publication order',
  'text': 'When publishing a new release:\n'
          '\n'
          '1. create ScipionAPI-vX.Y.Z.zip\n'
          '2. create ScipionWeb-vX.Y.Z-dist.zip\n'
          '3. generate or update manifest.json\n'
          '4. upload both ZIP files\n'
          '5. upload manifest.json last\n'
          '\n'
          'Uploading manifest.json last prevents users from seeing a latest version whose ZIP files are not yet '
          'available.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#publication-order'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Example production flow',
  'text': 'bash\n'
          './scripts/scipionapi update --dry-run\n'
          './scripts/scipionapi update --version v4.0.1\n'
          './scripts/scipionapi status\n'
          './scripts/scipionapi doctor --quick\n'
          './scripts/scipionapi logs\n'
          '\n'
          'Then verify the Web UI:\n'
          '\n'
          '- login\n'
          '- project list\n'
          '- project loading\n'
          '- one basic workflow or protocol action',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#example-production-flow'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Related endpoints',
  'text': 'ScipionAPI exposes system endpoints that ScipionWeb can use to show update information:\n'
          '\n'
          'http\n'
          'GET /api/system/version\n'
          'GET /api/system/update-check\n'
          '\n'
          'These endpoints are informational. They do not run the update automatically.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#related-endpoints'},
 {'area': 'cli',
  'page': 'update',
  'title': 'Related pages',
  'text': '- Upgrade Guide\n- Runtime Commands\n- Backup and Restore\n- Release Checklist',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/cli/update/#related-pages'},
 {'area': 'support',
  'page': 'Ask a Question',
  'title': 'Best support channel',
  'text': 'Use GitHub Discussions for questions, troubleshooting, and clarification:\n'
          '\n'
          '➡️ Open ScipionWeb Discussions\n'
          '\n'
          'That makes it easier to:\n'
          '\n'
          '- keep the conversation open\n'
          '- get feedback before opening a bug report\n'
          '- help future users who hit the same issue',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/ask-a-question/#best-support-channel'},
 {'area': 'support',
  'page': 'Ask a Question',
  'title': 'Good questions usually include',
  'text': '- ScipionWeb version or bundle version\n'
          '- ScipionAPI version if relevant\n'
          '- deployment mode (integrated, API-only, development)\n'
          '- operating system and relevant environment details\n'
          '- what you were trying to do\n'
          '- what actually happened\n'
          '- any visible error message\n'
          '- any relevant log excerpt or screenshot',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/ask-a-question/#good-questions-usually-include'},
 {'area': 'support',
  'page': 'Ask a Question',
  'title': 'Before asking',
  'text': 'Check these first:\n'
          '\n'
          '- Common Errors and Fixes\n'
          '- Backend Troubleshooting\n'
          '- Known Issues and Workarounds\n'
          '- ScipionWeb issue list',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/ask-a-question/#before-asking'},
 {'area': 'support',
  'page': 'Ask a Question',
  'title': 'Question template you can copy',
  'text': 'text\n'
          'Environment:\n'
          'ScipionWeb version:\n'
          'ScipionAPI version:\n'
          'Deployment mode:\n'
          'OS / runtime details:\n'
          '\n'
          'What I was trying to do:\n'
          '\n'
          'What happened instead:\n'
          '\n'
          'Error message or logs:\n'
          '\n'
          'What I already checked:',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/ask-a-question/#question-template-you-can-copy'},
 {'area': 'support',
  'page': 'Ask a Question',
  'title': 'When not to use this path',
  'text': 'If the behavior is clearly reproducible and you already have solid reproduction steps, use Report a Bug '
          'instead.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/ask-a-question/#when-not-to-use-this-path'},
 {'area': 'support',
  'page': 'Known Issues and Workarounds',
  'title': 'Celery tasks remain in `PENDING`',
  'text': 'Symptoms\n'
          '\n'
          '- A plugin installation, protocol execution, or background action is submitted successfully.\n'
          '- The task remains in PENDING for a long time.\n'
          '- The UI does not show task progress.\n'
          '\n'
          'Common causes\n'
          '\n'
          '- The Celery worker is not running.\n'
          '- Valkey is not reachable from the API or worker.\n'
          '- The API and worker are using different .env files or different broker URLs.\n'
          '- The worker started without the expected SCIPIONHOME.\n'
          '\n'
          'Checks\n'
          '\n'
          './scripts/scipionapi status\n'
          './scripts/scipionapi logs\n'
          'valkey-cli ping\n'
          '\n'
          'Expected Valkey response:\n'
          '\n'
          'text\n'
          'PONG\n'
          '\n'
          'Workaround\n'
          '\n'
          'Restart the runtime after verifying that SCIPIONHOME, CELERYBROKERURL, and CELERYRESULTBACKEND are '
          'consistent:\n'
          '\n'
          './scripts/scipionapi restart',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/known-issues/#celery-tasks-remain-in-pending'},
 {'area': 'support',
  'page': 'Known Issues and Workarounds',
  'title': 'Valkey broker reports no nodes replied within time constraint',
  'text': 'Symptoms\n'
          '\n'
          '- Celery status commands fail or time out.\n'
          '- Background tasks do not progress.\n'
          '- Logs mention that no Valkey nodes replied within the expected time.\n'
          '\n'
          'Common causes\n'
          '\n'
          '- Valkey is stopped or overloaded.\n'
          '- The configured broker URL points to the wrong Valkey host, port, or database.\n'
          '- Firewall or network restrictions block access in a distributed deployment.\n'
          '\n'
          'Checks\n'
          '\n'
          'sudo systemctl status valkey-server\n'
          'valkey-cli ping\n'
          '\n'
          'Workaround\n'
          '\n'
          'Start or restart Valkey, then restart ScipionAPI services:\n'
          '\n'
          'sudo systemctl restart valkey-server\n'
          './scripts/scipionapi restart',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/known-issues/#valkey-broker-reports-no-nodes-replied-within-time-constraint'},
 {'area': 'support',
  'page': 'Known Issues and Workarounds',
  'title': '`SCIPION_HOME` is not available in the worker',
  'text': 'Symptoms\n'
          '\n'
          '- The API starts, but Celery tasks fail immediately.\n'
          '- Worker logs mention missing runtime configuration or missing SCIPIONHOME.\n'
          '- Tasks behave differently when run from a shell and from the worker.\n'
          '\n'
          'Common causes\n'
          '\n'
          '- The worker was started from a shell that did not export SCIPIONHOME.\n'
          '- The worker process is not loading SCIPIONHOME/.env.\n'
          '- API and worker were started through different mechanisms.\n'
          '\n'
          'Checks\n'
          '\n'
          'echo "$SCIPIONHOME"\n'
          'test -f "$SCIPIONHOME/.env" && echo ".env found"\n'
          './scripts/scipionapi logs\n'
          '\n'
          'Workaround\n'
          '\n'
          'Start API and worker through the same runtime command so both processes share the same configuration '
          'source:\n'
          '\n'
          './scripts/scipionapi restart',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/known-issues/#scipion_home-is-not-available-in-the-worker'},
 {'area': 'support',
  'page': 'Known Issues and Workarounds',
  'title': '`ImportError`: `pyworkflow.project.manager` not found',
  'text': 'Symptoms\n'
          '\n'
          '- Backend startup or Celery worker startup fails.\n'
          '- Logs show an import error involving pyworkflow or pyworkflow.project.manager.\n'
          '\n'
          'Common causes\n'
          '\n'
          '- The wrong Conda environment is active.\n'
          '- Scipion dependencies were not installed in the environment used by the process.\n'
          '- The worker is started outside the wrapper script or expected environment.\n'
          '\n'
          'Checks\n'
          '\n'
          'conda activate scipion4Web\n'
          'python -c "import pyworkflow; print(pyworkflow.file)"\n'
          '\n'
          'Workaround\n'
          '\n'
          'Activate the expected environment and restart using the wrapper script from the ScipionAPI bundle '
          'directory:\n'
          '\n'
          'conda activate scipion4Web\n'
          './scripts/scipionapi restart',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/known-issues/#importerror-pyworkflowprojectmanager-not-found'},
 {'area': 'support',
  'page': 'Known Issues and Workarounds',
  'title': 'Browser CORS errors between frontend and backend',
  'text': 'Symptoms\n'
          '\n'
          '- Requests work with curl but fail in the browser.\n'
          '- Browser DevTools show CORS or preflight errors.\n'
          '- This often appears in development mode with the Web UI on localhost:5173 and the API on '
          'localhost:8080.\n'
          '\n'
          'Common causes\n'
          '\n'
          '- The frontend origin is not allowed by the backend.\n'
          '- The configured API URL does not match the real browser origin.\n'
          '- A reverse proxy changes scheme, host, or port unexpectedly.\n'
          '\n'
          'Checks\n'
          '\n'
          '- Confirm the exact frontend URL shown in the browser.\n'
          '- Confirm the backend CORS configuration includes that exact origin.\n'
          '- Check failed requests in browser DevTools.\n'
          '\n'
          'Workaround\n'
          '\n'
          'Add the exact frontend origin to the backend CORS configuration and restart the API.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/known-issues/#browser-cors-errors-between-frontend-and-backend'},
 {'area': 'support',
  'page': 'Known Issues and Workarounds',
  'title': 'Alembic cannot locate a revision',
  'text': 'Symptoms\n'
          '\n'
          "- Migration commands fail with a message similar to Can't locate revision identified by ....\n"
          '- Upgrade or install fails while applying database migrations.\n'
          '\n'
          'Common causes\n'
          '\n'
          '- The database migration history points to a revision that is not present in the current code checkout or '
          'bundle.\n'
          '- The wrong database is being targeted.\n'
          '- A partially applied migration state was left behind after a failed test or upgrade.\n'
          '\n'
          'Checks\n'
          '\n'
          'alembic current\n'
          'alembic heads\n'
          '\n'
          'Also confirm that DATABASEURL points to the intended database.\n'
          '\n'
          'Workaround\n'
          '\n'
          'For test databases, the simplest fix is often to recreate the database and apply migrations from a clean '
          'state.\n'
          '\n'
          'For real deployments, do not edit migration history blindly. Back up the database first, inspect the '
          'missing revision, and decide whether a controlled stamp or migration repair is appropriate.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/known-issues/#alembic-cannot-locate-a-revision'},
 {'area': 'support',
  'page': 'Known Issues and Workarounds',
  'title': 'Port `8080` already in use',
  'text': 'Symptoms\n'
          '\n'
          '- API startup fails with an address-in-use error.\n'
          '- provision or start appears to fail immediately.\n'
          '\n'
          'Checks\n'
          '\n'
          'lsof -i :8080\n'
          '\n'
          'Workaround\n'
          '\n'
          'Stop the process using the port, or configure ScipionAPI to use a different API port.\n'
          '\n'
          'Use forceful termination only as a last resort after confirming the process is safe to stop.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/known-issues/#port-8080-already-in-use'},
 {'area': 'support',
  'page': 'Known Issues and Workarounds',
  'title': 'When to add new entries',
  'text': 'Add a new entry here when the same issue appears repeatedly in development, installation, user support, '
          'or GitHub discussions.\n'
          '\n'
          'A useful entry should include symptoms, likely causes, checks, and a workaround.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/known-issues/#when-to-add-new-entries'},
 {'area': 'support',
  'page': 'Report a Bug',
  'title': 'Best support channel',
  'text': 'Use GitHub Issues for reproducible bugs:\n'
          '\n'
          '➡️ Open the issue chooser\n'
          '\n'
          'That gives you:\n'
          '\n'
          '- one report per problem\n'
          '- labels and prioritization\n'
          '- clear triage workflow\n'
          '- easier linking to fixes, commits, and releases',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/report-a-bug/#best-support-channel'},
 {'area': 'support',
  'page': 'Report a Bug',
  'title': 'A strong bug report includes',
  'text': '- exact environment and version\n'
          '- clear reproduction steps\n'
          '- expected behavior\n'
          '- actual behavior\n'
          '- relevant logs, traceback, or screenshots\n'
          '- whether the problem is new or was working before',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/report-a-bug/#a-strong-bug-report-includes'},
 {'area': 'support',
  'page': 'Report a Bug',
  'title': 'Before opening a bug report',
  'text': 'Check whether the problem may already be explained by:\n'
          '\n'
          '- configuration mismatch\n'
          '- stale browser session state\n'
          '- environment-specific dependency issues\n'
          '- a known issue already documented or discussed\n'
          '\n'
          'See also:\n'
          '\n'
          '- Ask a Question\n'
          '- Known Issues and Workarounds\n'
          '- ScipionWeb issue list',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/report-a-bug/#before-opening-a-bug-report'},
 {'area': 'support',
  'page': 'Report a Bug',
  'title': 'Bug report template you can copy',
  'text': 'text\n'
          'Environment:\n'
          'ScipionWeb version:\n'
          'ScipionAPI version:\n'
          'Deployment mode:\n'
          'OS / runtime details:\n'
          '\n'
          'Steps to reproduce:\n'
          '1.\n'
          '2.\n'
          '3.\n'
          '\n'
          'Expected behavior:\n'
          '\n'
          'Actual behavior:\n'
          '\n'
          'Logs / traceback / screenshots:\n'
          '\n'
          'Regression?:\n'
          'Did this work before?',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/report-a-bug/#bug-report-template-you-can-copy'},
 {'area': 'support',
  'page': 'Report a Bug',
  'title': 'When not to use this path',
  'text': 'If you are still unsure whether the behavior is a bug at all, start with Ask a Question in Discussions.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/report-a-bug/#when-not-to-use-this-path'},
 {'area': 'support',
  'page': 'Suggest an Improvement',
  'title': 'Best support channel',
  'text': 'Use GitHub Discussions first for open-ended ideas:\n'
          '\n'
          '➡️ Open ScipionWeb Discussions\n'
          '\n'
          'That helps clarify:\n'
          '\n'
          '- whether the idea solves a real recurring problem\n'
          '- whether other users want the same thing\n'
          '- whether the proposal should later become a feature request issue\n'
          '\n'
          'When an improvement becomes concrete and actionable, it can then move into GitHub Issues.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/suggest-an-improvement/#best-support-channel'},
 {'area': 'support',
  'page': 'Suggest an Improvement',
  'title': 'Good improvement proposals usually explain',
  'text': '- what part of ScipionWeb feels limited or awkward\n'
          '- who is affected by the problem\n'
          '- what the current workaround is, if any\n'
          '- what better outcome you would like to achieve\n'
          '- whether the idea is about UX, performance, reliability, or functionality',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/suggest-an-improvement/#good-improvement-proposals-usually-explain'},
 {'area': 'support',
  'page': 'Suggest an Improvement',
  'title': 'Improvement proposal template you can copy',
  'text': 'text\n'
          'Area affected:\n'
          'Who is affected:\n'
          '\n'
          'Current behavior:\n'
          '\n'
          'Why this is a problem:\n'
          '\n'
          'Suggested improvement:\n'
          '\n'
          'Workaround today:\n'
          '\n'
          'Additional context:',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/suggest-an-improvement/#improvement-proposal-template-you-can-copy'},
 {'area': 'support',
  'page': 'Suggest an Improvement',
  'title': 'When to turn an idea into an issue',
  'text': 'Open a GitHub Issue when the proposal becomes specific enough to track as planned work.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/support/suggest-an-improvement/#when-to-turn-an-idea-into-an-issue'}]
