"""The sections of the user guide (scipion-docs), for the help chat.

Written by scripts/build_help_guide.py: do not change it by hand."""

GUIDE = [{'page': 'Environment Variables in Settings',
  'title': 'What this page covers',
  'text': 'This page describes environment variables managed from the ScipionWeb interface.\n'
          '\n'
          'It is different from the server-side .env file used to configure ScipionAPI itself. For the low-level '
          'runtime file, see Environment Variables (.env).\n'
          '\n'
          'The Settings environment section is intended for variables that ScipionWeb and plugin execution need to '
          'read at runtime, especially path variables used by external scientific software.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#what-this-page-covers'},
 {'page': 'Environment Variables in Settings',
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
 {'page': 'Environment Variables in Settings',
  'title': 'Hot runtime assimilation',
  'text': 'ScipionWeb is able to assimilate these variables while the system is running. After a variable is created '
          'or modified from Settings, the updated value becomes available to the relevant ScipionWeb runtime context '
          'without forcing users to manually edit server files.\n'
          '\n'
          'Validate after changing variables:\n'
          'Even when ScipionWeb picks up the value dynamically, you should still validate the affected plugin or '
          'protocol after changing an environment variable.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#hot-runtime-assimilation'},
 {'page': 'Environment Variables in Settings',
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
 {'page': 'Environment Variables in Settings',
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
 {'page': 'Environment Variables in Settings',
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
 {'page': 'Environment Variables in Settings',
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
 {'page': 'Environment Variables in Settings',
  'title': 'Good practice',
  'text': '- keep variable names uppercase and consistent with plugin expectations\n'
          '- use absolute paths, not relative paths\n'
          '- avoid pointing variables to user-specific temporary folders\n'
          '- document externally managed software versions outside ScipionWeb when needed\n'
          '- test a minimal protocol after changing a plugin path\n'
          '- avoid duplicating binary installations when a stable external installation already exists',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/environment-variables/#good-practice'},
 {'page': 'Environment Variables in Settings',
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
 {'page': 'Environment Variables in Settings',
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
 {'page': 'First Login and Session Basics',
  'title': 'Before you troubleshoot login',
  'text': 'Confirm these basics first:\n'
          '\n'
          '- you are opening the intended environment\n'
          '- the backend instance is actually reachable\n'
          '- your browser is not reusing stale session state from another instance\n'
          '- you are not mixing tabs from different environments',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/first-login/#before-you-troubleshoot-login'},
 {'page': 'First Login and Session Basics',
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
 {'page': 'First Login and Session Basics',
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
 {'page': 'First Login and Session Basics',
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
 {'page': 'First Login and Session Basics',
  'title': 'Good habits for multi-environment work',
  'text': 'If you regularly switch between local, staging, and production:\n'
          '\n'
          '- keep those environments in clearly named bookmarks\n'
          '- avoid leaving old tabs open for long periods\n'
          '- confirm the URL before changing protected data\n'
          '- do not assume a saved session belongs to the environment you intend to use now',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/first-login/#good-habits-for-multi-environment-work'},
 {'page': 'First Login and Session Basics',
  'title': 'When to ask an administrator for help',
  'text': 'Ask for help when:\n'
          '\n'
          '- the same issue reproduces across browsers or machines\n'
          '- your account should exist but access is denied\n'
          '- the instance is reachable but protected data never loads\n'
          '- the backend appears healthy but login still fails consistently',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/first-login/#when-to-ask-an-administrator-for-help'},
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
  'title': 'Validate SLURM before connecting ScipionWeb',
  'text': 'Before configuring ScipionWeb, validate SLURM directly with small CPU and GPU jobs.\n'
          '\n'
          'CPU test:\n'
          '\n'
          'bash\n'
          'cat > /tmp/testslurmcpu.sh   /tmp/testslurmgpu.sh   Host\n'
          '5. run a small Scipion protocol through the queue',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/hosts-and-queues/#validate-slurm-before-connecting-scipionweb'},
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Hosts and Queues',
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
 {'page': 'Outputs and Viewers',
  'title': 'Typical output workflow',
  'text': 'After a protocol finishes, you will usually:\n'
          '\n'
          '1. locate the generated outputs in the protocol card, protocol details, or output area\n'
          '2. confirm that the protocol finished successfully\n'
          '3. open the relevant preview or viewer\n'
          '4. inspect the data in the context of the project and protocol history\n'
          '5. decide whether a downstream protocol can use that output',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#typical-output-workflow'},
 {'page': 'Outputs and Viewers',
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
 {'page': 'Outputs and Viewers',
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
 {'page': 'Outputs and Viewers',
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
 {'page': 'Outputs and Viewers',
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
 {'page': 'Outputs and Viewers',
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
 {'page': 'Outputs and Viewers',
  'title': 'Good practice',
  'text': 'When possible:\n'
          '\n'
          '- review outputs soon after execution finishes\n'
          '- compare what you see with what the workflow stage should produce\n'
          '- confirm that downstream steps are using the intended outputs\n'
          '- avoid relying only on memory when multiple similar runs exist in the same project',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/outputs/#good-practice'},
 {'page': 'Plugins',
  'title': 'Typical plugin-related tasks',
  'text': 'In normal use, you may need to:\n'
          '\n'
          '- review available plugins\n'
          '- check whether a plugin is already installed\n'
          '- start an installation or removal flow\n'
          '- monitor plugin-related task progress\n'
          '- confirm that the UI reflects the new plugin state',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/plugins/#typical-plugin-related-tasks'},
 {'page': 'Plugins',
  'title': 'What to verify before changing plugin state',
  'text': '- you are working in the intended environment\n'
          '- the backend and worker are running correctly\n'
          '- Valkey and Celery are healthy\n'
          '- the plugin action is allowed for your role or workflow\n'
          '- you understand whether the change affects only your current workflow or the whole instance',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/plugins/#what-to-verify-before-changing-plugin-state'},
 {'page': 'Plugins',
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
 {'page': 'Plugins',
  'title': 'Common plugin pitfalls',
  'text': 'Problems often appear when:\n'
          '\n'
          '- the UI shows stale plugin state after a change\n'
          '- the worker is unhealthy even though the API is reachable\n'
          '- environment-specific dependencies break an installation flow\n'
          '- a user assumes a plugin is globally available because it was available elsewhere',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/plugins/#common-plugin-pitfalls'},
 {'page': 'Plugins',
  'title': 'If a plugin operation gets stuck',
  'text': 'Check:\n'
          '\n'
          '- worker logs\n'
          '- Valkey availability\n'
          '- task status endpoint responses\n'
          '- whether the plugin introduced environment-specific dependency issues\n'
          '- whether the final state requires a refresh, restart, or explicit reload of backend-managed data',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/plugins/#if-a-plugin-operation-gets-stuck'},
 {'page': 'Projects',
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
 {'page': 'Projects',
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
 {'page': 'Projects',
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
 {'page': 'Projects',
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
 {'page': 'Projects',
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
 {'page': 'Projects',
  'title': 'Project hygiene recommendations',
  'text': '- keep names consistent\n'
          '- avoid near-duplicate project labels\n'
          '- review old projects deliberately instead of letting them accumulate without context\n'
          '- document collaboration expectations when the same project is shared by several users\n'
          '- prefer clarity over short-lived convenience in naming and organization',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/projects/#project-hygiene-recommendations'},
 {'page': 'Projects',
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
 {'page': 'Protocol Execution',
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
 {'page': 'Protocol Execution',
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
 {'page': 'Protocol Execution',
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
 {'page': 'Protocol Execution',
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
 {'page': 'Protocol Execution',
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
 {'page': 'Protocol Execution',
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
 {'page': 'Protocol Execution',
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
 {'page': 'Protocol Execution',
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
 {'page': 'Settings',
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
 {'page': 'Settings',
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
 {'page': 'Settings',
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
 {'page': 'Settings',
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
 {'page': 'Settings',
  'title': 'Good practice',
  'text': '- change one setting at a time\n'
          '- save and validate before making another change\n'
          '- document shared conventions for tags, environment variables, and queues\n'
          '- avoid changing host or queue settings while protocols are being launched or debugged\n'
          '- avoid changing runtime paths without validating the affected plugin\n'
          '- keep queue names aligned with the real scheduler configuration\n'
          '- prefer clear names and conservative defaults over ad-hoc values',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/settings/#good-practice'},
 {'page': 'Settings',
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
 {'page': 'Settings',
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
 {'page': 'Sharing and Collaboration',
  'title': 'Typical sharing workflow',
  'text': 'A common collaboration flow usually includes:\n'
          '\n'
          '1. confirming the correct project is selected\n'
          '2. granting access to the intended teammate\n'
          '3. verifying that the collaborator can open the project\n'
          '4. keeping naming and ownership expectations clear',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sharing/#typical-sharing-workflow'},
 {'page': 'Sharing and Collaboration',
  'title': 'Before sharing a project',
  'text': 'Check these basics first:\n'
          '\n'
          '- you are in the intended environment\n'
          '- the project is really the one meant for collaboration\n'
          '- the target user exists in the same instance\n'
          '- your team agrees on how project changes will be coordinated',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sharing/#before-sharing-a-project'},
 {'page': 'Sharing and Collaboration',
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
 {'page': 'Sharing and Collaboration',
  'title': 'Common collaboration pitfalls',
  'text': 'Problems often appear when:\n'
          '\n'
          '- a similarly named project is shared by mistake\n'
          '- two users assume different workflow stages are current\n'
          '- high-impact actions happen without coordination\n'
          '- one user is working in a different environment than the others',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sharing/#common-collaboration-pitfalls'},
 {'page': 'Sharing and Collaboration',
  'title': 'If sharing does not work as expected',
  'text': 'Check:\n'
          '\n'
          '- whether the intended user exists in the instance\n'
          '- whether the share action completed successfully\n'
          '- whether the collaborator is logged into the correct environment\n'
          '- whether browser requests return auth or permission errors\n'
          '- whether stale session state is hiding recent permission changes',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sharing/#if-sharing-does-not-work-as-expected'},
 {'page': 'Sign Up',
  'title': 'When to use sign-up',
  'text': 'Use the sign-up form when:\n'
          '\n'
          '- you are accessing a ScipionWeb instance for the first time\n'
          '- an administrator has asked you to create your own user account\n'
          '- your institution or team uses self-registration for new users\n'
          '\n'
          'If you already have credentials, go directly to First Login and Session Basics.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#when-to-use-sign-up'},
 {'page': 'Sign Up',
  'title': 'Open the sign-up page',
  'text': 'From the login screen, choose the sign-up option to open the registration form.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#open-the-sign-up-page'},
 {'page': 'Sign Up',
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
 {'page': 'Sign Up',
  'title': 'Submit the form',
  'text': 'After submitting the form, the account is created immediately. You can then continue to the login page '
          'and sign in with the credentials you just registered.\n'
          '\n'
          'If registration is disabled or restricted on a specific deployment, the form will not be available or the '
          'request may be rejected. In that case, contact the instance administrator.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#submit-the-form'},
 {'page': 'Sign Up',
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
 {'page': 'Sign Up',
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
 {'page': 'Sign Up',
  'title': 'Good practices',
  'text': '- Use a recognizable username or email address.\n'
          '- Do not share accounts between users.\n'
          '- Keep your password private.\n'
          '- Confirm that you are signing up on the intended ScipionWeb instance.\n'
          '- Use separate accounts for local, staging, and production instances when required.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/sign-up/#good-practices'},
 {'page': 'Tags',
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
 {'page': 'Tags',
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
 {'page': 'Tags',
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
 {'page': 'Tags',
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
 {'page': 'Tags',
  'title': 'Edit or delete existing tags',
  'text': 'Use editing when the tag is still useful but its name, description, or color needs improvement.\n'
          '\n'
          'Use deletion only when the tag is no longer part of the project convention.\n'
          '\n'
          'Before deleting a tag, check whether it is already assigned to protocols. Removing a tag can make the '
          'workflow harder to interpret if collaborators were using it as part of their review process.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#edit-or-delete-existing-tags'},
 {'page': 'Tags',
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
 {'page': 'Tags',
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
 {'page': 'Tags',
  'title': 'Good practice',
  'text': '- define a small tag set first and expand only when needed\n'
          '- use colors consistently across related projects when possible\n'
          '- document team-specific meanings in tag descriptions\n'
          '- keep tag names short enough to remain readable on protocol cards\n'
          '- remove obsolete tags only after checking their current assignments\n'
          '- avoid using tags as a substitute for protocol comments or execution status',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/tags/#good-practice'},
 {'page': 'Tags',
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
 {'page': 'Tags',
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
 {'page': 'Working Efficiently',
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
 {'page': 'Working Efficiently',
  'title': '2. Prefer clear naming over fast naming',
  'text': 'Use names that help you and your teammates answer basic questions quickly:\n'
          '\n'
          '- what is this project about?\n'
          '- which dataset or experiment does it represent?\n'
          '- is this the current workflow or an older attempt?\n'
          '\n'
          'Good names reduce mistakes later in protocol execution, sharing, and output review.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#2-prefer-clear-naming-over-fast-naming'},
 {'page': 'Working Efficiently',
  'title': '3. Treat save and launch as different moments',
  'text': 'A good mental model is:\n'
          '\n'
          '- configure carefully\n'
          '- save intentionally\n'
          '- launch only when the saved state is the one you want\n'
          '\n'
          'This helps avoid confusion about whether a protocol was merely edited or actually executed.',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#3-treat-save-and-launch-as-different-moments'},
 {'page': 'Working Efficiently',
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
 {'page': 'Working Efficiently',
  'title': '5. Coordinate shared work explicitly',
  'text': 'In collaborative environments:\n'
          '\n'
          '- communicate before high-impact project actions\n'
          '- make it clear which project state is current\n'
          '- avoid silent assumptions about who validated which outputs\n'
          '- keep naming and ownership conventions stable',
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#5-coordinate-shared-work-explicitly'},
 {'page': 'Working Efficiently',
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
 {'page': 'Working Efficiently',
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
  'url': 'https://fonsecareyna82.github.io/scipion-docs/user-guide/working-efficiently/#7-recheck-before-assuming-the-system-is-wrong'}]
