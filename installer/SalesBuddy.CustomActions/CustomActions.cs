using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using WixToolset.Dtf.WindowsInstaller;

namespace SalesBuddy.CustomActions
{
    /// <summary>
    /// WiX DTF custom actions for Sales Buddy installation and uninstallation.
    /// Each [CustomAction] method is an entry point callable from the MSI.
    /// All external processes run with CreateNoWindow=true (no terminal windows).
    /// Status text updates are pushed to the MSI progress page in real time.
    /// </summary>
    public class InstallerActions
    {
        // =====================================================================
        // Configuration
        // =====================================================================

        private const string RepoUrl = "https://github.com/rablaine/SalesBuddy.git";
        private const int DefaultPort = 5151;
        private const string AppName = "Sales Buddy";
        private const string PythonVersion = "3.13.2";
        private const string PythonNuGetUrl =
            "https://www.nuget.org/api/v2/package/python/" + PythonVersion;
        private const string NodeVersion = "v22.14.0";
        private const string NodeZipUrl =
            "https://nodejs.org/dist/" + NodeVersion + "/node-" + NodeVersion + "-win-x64.zip";

        // Step weights for progress bar (total = 100).
        private const int WeightWinget = 5;
        private const int WeightGit = 10;
        private const int WeightPython = 10;
        private const int WeightAzCli = 30;
        private const int WeightNode = 8;
        private const int WeightClone = 10;
        private const int WeightVenv = 15;
        private const int WeightConfig = 3;
        private const int WeightShortcuts = 2;
        private const int WeightAutoStart = 2;
        private const int WeightServer = 3;
        private const int WeightFinish = 2;

        // =====================================================================
        // Entry points
        // =====================================================================

        /// <summary>
        /// Main install action. Orchestrates all installation steps with
        /// live progress bar and status text updates in the MSI UI.
        /// Called as a deferred custom action after InstallFiles.
        /// </summary>
        [CustomAction]
        public static ActionResult InstallAction(Session session)
        {
            session.Log("=== Sales Buddy Installation Starting ===");

            // TLS 1.2 for all downloads (GitHub, NuGet, nodejs.org)
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;

            // Read properties passed via CustomActionData
            var data = session.CustomActionData;
            string installDir = data.ContainsKey("INSTALLFOLDER")
                ? data["INSTALLFOLDER"]
                : Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "SalesBuddy");

            bool startMenu = GetBoolData(data, "STARTMENUSHORTCUT");
            bool desktop = GetBoolData(data, "DESKTOPSHORTCUT");
            bool launchBrowser = GetBoolData(data, "LAUNCHBROWSER");
            bool autoStart = GetBoolData(data, "AUTOSTART");

            session.Log($"Install directory: {installDir}");
            session.Log($"Options: StartMenu={startMenu}, Desktop={desktop}, " +
                        $"Launch={launchBrowser}, AutoStart={autoStart}");

            // Initialize progress bar (tell MSI how many ticks we'll report)
            InitProgress(session, 100);

            try
            {
                // Refresh PATH so we can find already-installed tools
                PathHelper.RefreshPath();

                // Step 1: Winget
                ProcessRunner.UpdateStatus(session, "Checking for winget...");
                EnsureWinget(session);
                AdvanceProgress(session, WeightWinget);

                // Step 2: Git
                ProcessRunner.UpdateStatus(session, "Checking for Git...");
                EnsureGit(session);
                AdvanceProgress(session, WeightGit);

                // Step 3: Python
                ProcessRunner.UpdateStatus(session, "Checking for Python...");
                EnsurePython(session);
                AdvanceProgress(session, WeightPython);

                // Step 4: Azure CLI (the big one - 3-5 minutes)
                ProcessRunner.UpdateStatus(session,
                    "Installing Azure CLI... this takes a few minutes");
                EnsureAzureCli(session);
                AdvanceProgress(session, WeightAzCli);

                // Step 5: Node.js
                ProcessRunner.UpdateStatus(session, "Checking for Node.js...");
                EnsureNodeJs(session);
                AdvanceProgress(session, WeightNode);

                // Verify critical commands before proceeding
                PathHelper.RefreshPath();
                PrependLocalTools();
                foreach (var cmd in new[] { "git", "python" })
                {
                    if (!PathHelper.CommandExists(cmd))
                    {
                        session.Log($"FATAL: {cmd} not found on PATH after installation.");
                        return ActionResult.Failure;
                    }
                }

                // Step 6: Clone/update repository
                ProcessRunner.UpdateStatus(session, "Setting up Sales Buddy...");
                CloneOrUpdateRepo(session, installDir);
                AdvanceProgress(session, WeightClone);

                // Step 7: Python environment (venv + pip install)
                ProcessRunner.UpdateStatus(session, "Setting up Python environment...");
                SetupPythonEnv(session, installDir);
                AdvanceProgress(session, WeightVenv);

                // Step 8: Configure app (.env + migrations)
                ProcessRunner.UpdateStatus(session, "Configuring application...");
                ConfigureApp(session, installDir);
                AdvanceProgress(session, WeightConfig);

                // Step 9: Shortcuts
                if (startMenu || desktop)
                {
                    ProcessRunner.UpdateStatus(session, "Creating shortcuts...");
                    CreateShortcuts(session, installDir, startMenu, desktop);
                }
                AdvanceProgress(session, WeightShortcuts);

                // Step 10: Auto-start
                if (autoStart)
                {
                    ProcessRunner.UpdateStatus(session, "Configuring auto-start...");
                    ConfigureAutoStartTask(session, installDir);
                }
                AdvanceProgress(session, WeightAutoStart);

                // Step 11: Start server
                ProcessRunner.UpdateStatus(session, "Starting Sales Buddy server...");
                StartServer(session, installDir);
                AdvanceProgress(session, WeightServer);

                // Step 12: Launch browser
                if (launchBrowser)
                {
                    int port = GetPortFromEnv(installDir);
                    string url = $"http://localhost:{port}";
                    ProcessRunner.UpdateStatus(session, $"Opening {url}...");
                    Process.Start("explorer.exe", url);
                }
                AdvanceProgress(session, WeightFinish);

                ProcessRunner.UpdateStatus(session, "Installation complete!");
                session.Log("=== Sales Buddy Installation Complete ===");
                return ActionResult.Success;
            }
            catch (InstallCanceledException)
            {
                session.Log("Installation cancelled by user.");
                return ActionResult.UserExit;
            }
            catch (Exception ex)
            {
                session.Log($"FATAL: {ex}");
                ProcessRunner.UpdateStatus(session,
                    "Installation failed. Check the log for details.");
                return ActionResult.Failure;
            }
        }

        /// <summary>
        /// Uninstall action. Stops the server, removes scheduled tasks,
        /// shortcuts, and app files. Backs up the database first.
        /// Called as a deferred custom action before RemoveFiles.
        /// </summary>
        [CustomAction]
        public static ActionResult UninstallAction(Session session)
        {
            session.Log("=== Sales Buddy Uninstall Starting ===");

            var data = session.CustomActionData;
            string installDir = data.ContainsKey("INSTALLFOLDER")
                ? data["INSTALLFOLDER"]
                : Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "SalesBuddy");

            try
            {
                // Stop the running server
                ProcessRunner.UpdateStatus(session, "Stopping Sales Buddy server...");
                StopServer(session, installDir);

                // Remove scheduled tasks
                ProcessRunner.UpdateStatus(session, "Removing scheduled tasks...");
                RemoveScheduledTasks(session);

                // Remove shortcuts
                ProcessRunner.UpdateStatus(session, "Removing shortcuts...");
                RemoveShortcuts(session);

                // Backup database
                string dbFile = Path.Combine(installDir, "data", "salesbuddy.db");
                if (File.Exists(dbFile))
                {
                    string timestamp = DateTime.Now.ToString("yyyyMMdd-HHmmss");
                    string backup = Path.Combine(Path.GetTempPath(),
                        $"salesbuddy-uninstall-{timestamp}.db");
                    ProcessRunner.UpdateStatus(session, "Backing up database...");
                    File.Copy(dbFile, backup, true);
                    session.Log($"Database backed up to {backup}");
                }

                // Remove app files
                ProcessRunner.UpdateStatus(session, "Removing application files...");
                if (Directory.Exists(installDir))
                {
                    try
                    {
                        Directory.Delete(installDir, true);
                        session.Log("App files removed.");
                    }
                    catch (Exception ex)
                    {
                        session.Log($"Could not fully remove {installDir}: {ex.Message}");
                    }
                }

                ProcessRunner.UpdateStatus(session, "Uninstall complete.");
                session.Log("=== Sales Buddy Uninstall Complete ===");
                return ActionResult.Success;
            }
            catch (Exception ex)
            {
                session.Log($"Uninstall error: {ex}");
                return ActionResult.Success; // Don't block uninstall on errors
            }
        }

        // =====================================================================
        // Progress helpers
        // =====================================================================

        /// <summary>
        /// Tell the MSI engine how many progress ticks our custom action will report.
        /// Must be called once at the start before any AdvanceProgress calls.
        /// </summary>
        private static void InitProgress(Session session, int totalTicks)
        {
            using (var record = new Record(4))
            {
                record[1] = 3; // Type 3 = add ticks to the total
                record[2] = totalTicks;
                record[3] = 0;
                record[4] = 0;
                session.Message(InstallMessage.Progress, record);
            }
        }

        /// <summary>
        /// Advance the MSI progress bar by the specified number of ticks.
        /// </summary>
        private static void AdvanceProgress(Session session, int ticks)
        {
            using (var record = new Record(2))
            {
                record[1] = 2; // Type 2 = increment
                record[2] = ticks;
                session.Message(InstallMessage.Progress, record);
            }
        }

        // =====================================================================
        // Prerequisite steps
        // =====================================================================

        /// <summary>
        /// Ensure winget is available. If not found, install it from GitHub.
        /// </summary>
        private static void EnsureWinget(Session session)
        {
            if (PathHelper.FindWinget(session))
            {
                session.Log("winget already available.");
                ProcessRunner.UpdateStatus(session, "winget found, skipping...");
                return;
            }

            session.Log("winget not found. Installing from GitHub...");
            ProcessRunner.UpdateStatus(session, "Installing winget...");

            // The winget bootstrap requires Add-AppxPackage (PowerShell cmdlet).
            // We run it as a hidden PowerShell process - no terminal window.
            string script = @"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ErrorActionPreference = 'Stop'

# VCLibs dependency
$vcLibsUrl = 'https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx'
$vcLibsPath = Join-Path $env:TEMP 'VCLibs.appx'
Write-Host 'Downloading VCLibs...'
Invoke-WebRequest -Uri $vcLibsUrl -OutFile $vcLibsPath -UseBasicParsing
Add-AppxPackage -Path $vcLibsPath -ErrorAction SilentlyContinue

# UI.Xaml from NuGet
$xamlUrl = 'https://www.nuget.org/api/v2/package/Microsoft.UI.Xaml/2.8.6'
$xamlZip = Join-Path $env:TEMP 'UIXaml.nupkg.zip'
$xamlDir = Join-Path $env:TEMP 'UIXaml-nupkg'
Write-Host 'Downloading UI.Xaml...'
Invoke-WebRequest -Uri $xamlUrl -OutFile $xamlZip -UseBasicParsing
if (Test-Path $xamlDir) { Remove-Item $xamlDir -Recurse -Force }
Expand-Archive -Path $xamlZip -DestinationPath $xamlDir -Force
$appx = Join-Path $xamlDir 'tools\AppX\x64\Release\Microsoft.UI.Xaml.2.8.appx'
if (Test-Path $appx) { Add-AppxPackage -Path $appx -ErrorAction SilentlyContinue }

# winget from GitHub
Write-Host 'Downloading winget...'
$release = Invoke-RestMethod -Uri 'https://api.github.com/repos/microsoft/winget-cli/releases/latest' -UseBasicParsing
$msixUrl = ($release.assets | Where-Object { $_.name -match '\.msixbundle$' }).browser_download_url
$licUrl = ($release.assets | Where-Object { $_.name -match 'License.*\.xml$' }).browser_download_url
$msixPath = Join-Path $env:TEMP 'winget.msixbundle'
Invoke-WebRequest -Uri $msixUrl -OutFile $msixPath -UseBasicParsing

if ($licUrl) {
    $licPath = Join-Path $env:TEMP 'winget-license.xml'
    Invoke-WebRequest -Uri $licUrl -OutFile $licPath -UseBasicParsing
    try {
        Add-AppxProvisionedPackage -Online -PackagePath $msixPath -LicensePath $licPath -ErrorAction Stop
        Write-Host 'winget provisioned system-wide.'
    } catch {
        Write-Host 'Provisioned install failed (expected if not admin). Falling back...'
    }
}
Add-AppxPackage -Path $msixPath -ErrorAction SilentlyContinue

# Ensure WindowsApps is on PATH
$wa = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps'
if ($env:Path -notlike ""*$wa*"") { $env:Path += "";$wa"" }
Write-Host 'winget installation complete.'
";

            int exitCode = ProcessRunner.RunPowerShell(session, script, "  ");
            PathHelper.RefreshPath();

            // Add WindowsApps to our process PATH
            var windowsApps = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Microsoft", "WindowsApps");
            PathHelper.AddToPath(windowsApps);

            if (PathHelper.FindWinget(session))
            {
                session.Log("winget installed successfully.");
            }
            else
            {
                session.Log("winget installation completed but command not found. Continuing...");
            }
        }

        /// <summary>
        /// Ensure Git is installed. Uses winget if available.
        /// </summary>
        private static void EnsureGit(Session session)
        {
            PathHelper.RefreshPath();
            if (PathHelper.CommandExists("git"))
            {
                session.Log("Git already installed.");
                ProcessRunner.UpdateStatus(session, "Git already installed, skipping...");
                return;
            }

            if (!PathHelper.CommandExists("winget"))
            {
                session.Log("winget not available. Cannot install Git automatically.");
                return;
            }

            ProcessRunner.UpdateStatus(session,
                "Installing Git... this may take a minute or two");
            InstallViaWinget(session, "Git", "Git.Git", "git");
        }

        /// <summary>
        /// Ensure Python is installed. Uses NuGet zip extraction (no MSI mutex conflict).
        /// </summary>
        private static void EnsurePython(Session session)
        {
            PathHelper.RefreshPath();
            if (PathHelper.CommandExists("python"))
            {
                session.Log("Python already installed.");
                ProcessRunner.UpdateStatus(session, "Python already installed, skipping...");
                return;
            }

            ProcessRunner.UpdateStatus(session, $"Installing Python {PythonVersion}...");

            var localAppData = Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData);
            var pythonDir = Path.Combine(localAppData, "python");
            var tempZip = Path.Combine(Path.GetTempPath(),
                $"python-{PythonVersion}.nupkg.zip");
            var extractDir = Path.Combine(Path.GetTempPath(), "python-nupkg");

            try
            {
                // Download Python NuGet package
                ProcessRunner.UpdateStatus(session,
                    $"Downloading Python {PythonVersion}...");
                DownloadFile(session, PythonNuGetUrl, tempZip);

                // Extract
                ProcessRunner.UpdateStatus(session, "Extracting Python...");
                if (Directory.Exists(extractDir))
                    Directory.Delete(extractDir, true);
                ZipFile.ExtractToDirectory(tempZip, extractDir);

                // NuGet python package has the full CPython in tools/
                var toolsDir = Path.Combine(extractDir, "tools");
                if (!Directory.Exists(toolsDir) ||
                    !File.Exists(Path.Combine(toolsDir, "python.exe")))
                {
                    session.Log("Python tools/ directory not found in NuGet package.");
                    return;
                }

                // Move to final location
                if (Directory.Exists(pythonDir))
                    Directory.Delete(pythonDir, true);
                Directory.Move(toolsDir, pythonDir);

                // Add to PATH (prepend to beat the WindowsApps Store stub)
                var scriptsDir = Path.Combine(pythonDir, "Scripts");
                PathHelper.AddToPath(pythonDir, persist: true);
                PathHelper.AddToPath(scriptsDir, persist: true);

                // Bootstrap pip
                ProcessRunner.UpdateStatus(session, "Bootstrapping pip...");
                var pythonExe = Path.Combine(pythonDir, "python.exe");
                ProcessRunner.Run(session, pythonExe,
                    "-m ensurepip --upgrade", "  ");

                session.Log($"Python {PythonVersion} installed to {pythonDir}.");
            }
            catch (Exception ex)
            {
                session.Log($"Failed to install Python: {ex.Message}");
            }
            finally
            {
                CleanupTemp(tempZip, extractDir);
            }
        }

        /// <summary>
        /// Ensure Azure CLI is installed. Uses pip install (no MSI mutex conflict).
        /// This is the slowest step - 3-5 minutes. Status text updates per package.
        /// </summary>
        private static void EnsureAzureCli(Session session)
        {
            PathHelper.RefreshPath();
            if (PathHelper.CommandExists("az"))
            {
                session.Log("Azure CLI already installed.");
                ProcessRunner.UpdateStatus(session,
                    "Azure CLI already installed, skipping...");
                return;
            }

            ProcessRunner.UpdateStatus(session,
                "Installing Azure CLI... this takes a few minutes");

            var pythonExe = PathHelper.FindPython();
            if (pythonExe == null)
            {
                session.Log("Python not found. Cannot install Azure CLI.");
                return;
            }

            // pip install azure-cli with line-by-line status updates
            int exitCode = ProcessRunner.Run(session, pythonExe,
                "-m pip install azure-cli",
                "  ");

            PathHelper.RefreshPath();

            if (PathHelper.CommandExists("az"))
            {
                session.Log("Azure CLI installed successfully.");
            }
            else
            {
                // pip puts az.cmd in Python's Scripts dir - ensure it's on PATH
                var pythonDir = Path.GetDirectoryName(pythonExe);
                var scriptsDir = Path.Combine(pythonDir, "Scripts");
                if (File.Exists(Path.Combine(scriptsDir, "az.cmd")))
                {
                    PathHelper.AddToPath(scriptsDir);
                    session.Log($"Azure CLI installed (added {scriptsDir} to PATH).");
                }
                else
                {
                    session.Log("Azure CLI pip install completed but 'az' not found.");
                }
            }
        }

        /// <summary>
        /// Ensure Node.js is installed. Uses zip extraction (no MSI mutex conflict).
        /// </summary>
        private static void EnsureNodeJs(Session session)
        {
            PathHelper.RefreshPath();
            if (PathHelper.CommandExists("node"))
            {
                session.Log("Node.js already installed.");
                ProcessRunner.UpdateStatus(session,
                    "Node.js already installed, skipping...");
                return;
            }

            ProcessRunner.UpdateStatus(session, $"Installing Node.js {NodeVersion}...");

            var localAppData = Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData);
            var nodeDir = Path.Combine(localAppData, "nodejs");
            var tempZip = Path.Combine(Path.GetTempPath(),
                $"node-{NodeVersion}-win-x64.zip");
            var extractDir = Path.Combine(Path.GetTempPath(), "nodejs-extract");

            try
            {
                ProcessRunner.UpdateStatus(session,
                    $"Downloading Node.js {NodeVersion}...");
                DownloadFile(session, NodeZipUrl, tempZip);

                ProcessRunner.UpdateStatus(session, "Extracting Node.js...");
                if (Directory.Exists(extractDir))
                    Directory.Delete(extractDir, true);
                ZipFile.ExtractToDirectory(tempZip, extractDir);

                // Node.js zip has an inner directory like "node-v22.14.0-win-x64"
                var innerDirs = Directory.GetDirectories(extractDir);
                if (innerDirs.Length == 0)
                {
                    session.Log("Node.js zip extraction produced no directories.");
                    return;
                }

                if (Directory.Exists(nodeDir))
                    Directory.Delete(nodeDir, true);
                Directory.Move(innerDirs[0], nodeDir);

                PathHelper.AddToPath(nodeDir, persist: true);
                session.Log($"Node.js {NodeVersion} installed to {nodeDir}.");
            }
            catch (Exception ex)
            {
                session.Log($"Failed to install Node.js: {ex.Message}");
            }
            finally
            {
                CleanupTemp(tempZip, extractDir);
            }
        }

        // =====================================================================
        // App setup steps
        // =====================================================================

        /// <summary>
        /// Clone the Sales Buddy repo or update an existing clone.
        /// Disables Git Credential Manager prompts (public repo).
        /// </summary>
        private static void CloneOrUpdateRepo(Session session, string installDir)
        {
            // Disable GCM popups
            Environment.SetEnvironmentVariable("GIT_TERMINAL_PROMPT", "0");
            Environment.SetEnvironmentVariable("GCM_INTERACTIVE", "never");

            string gitDir = Path.Combine(installDir, ".git");
            if (Directory.Exists(gitDir))
            {
                // Existing repo - fetch and reset
                ProcessRunner.UpdateStatus(session, "Updating Sales Buddy repository...");
                session.Log("Repository exists, pulling latest.");
                ProcessRunner.Run(session, "git",
                    "-c credential.helper= fetch origin",
                    workingDirectory: installDir);
                ProcessRunner.Run(session, "git",
                    "reset --hard origin/main",
                    workingDirectory: installDir);
                ProcessRunner.Run(session, "git",
                    "clean -fd",
                    workingDirectory: installDir);
            }
            else if (Directory.Exists(installDir))
            {
                // Directory exists but not a git repo (MSI created it for icon.ico).
                // Initialize in-place.
                ProcessRunner.UpdateStatus(session,
                    "Initializing Sales Buddy repository...");
                session.Log("Directory exists, initializing git repo in-place.");
                ProcessRunner.Run(session, "git", "init",
                    workingDirectory: installDir);
                ProcessRunner.Run(session, "git",
                    $"remote add origin {RepoUrl}",
                    workingDirectory: installDir);
                ProcessRunner.Run(session, "git",
                    "-c credential.helper= fetch origin",
                    workingDirectory: installDir);
                ProcessRunner.Run(session, "git",
                    "checkout -f -B main origin/main",
                    workingDirectory: installDir);
            }
            else
            {
                // Fresh clone
                ProcessRunner.UpdateStatus(session,
                    "Cloning Sales Buddy repository...");
                PathHelper.RefreshPath();
                int exitCode = ProcessRunner.Run(session, "git",
                    $"-c credential.helper= clone {RepoUrl} \"{installDir}\"");
                if (exitCode != 0)
                {
                    throw new InvalidOperationException(
                        $"git clone failed with exit code {exitCode}");
                }
            }

            session.Log("Repository ready.");
        }

        /// <summary>
        /// Create a Python virtual environment and install dependencies.
        /// </summary>
        private static void SetupPythonEnv(Session session, string installDir)
        {
            var pythonExe = PathHelper.FindPython();
            if (pythonExe == null)
                throw new InvalidOperationException("Python not found.");

            var venvPython = Path.Combine(installDir, "venv", "Scripts", "python.exe");
            var pipExe = Path.Combine(installDir, "venv", "Scripts", "pip.exe");
            var reqFile = Path.Combine(installDir, "requirements.txt");

            // Create venv if it doesn't exist
            if (!File.Exists(venvPython))
            {
                ProcessRunner.UpdateStatus(session,
                    "Creating Python virtual environment...");
                var venvDir = Path.Combine(installDir, "venv");
                ProcessRunner.Run(session, pythonExe, $"-m venv \"{venvDir}\"");
                if (!File.Exists(venvPython))
                    throw new InvalidOperationException("Failed to create venv.");
                session.Log("Virtual environment created.");
            }
            else
            {
                session.Log("Virtual environment already exists.");
            }

            // pip install requirements
            if (File.Exists(reqFile))
            {
                ProcessRunner.UpdateStatus(session,
                    "Installing Python dependencies...");
                ProcessRunner.Run(session, pipExe,
                    $"install -r \"{reqFile}\"",
                    "  ");
                session.Log("Dependencies installed.");
            }
        }

        /// <summary>
        /// Create .env file from template and run database migrations.
        /// </summary>
        private static void ConfigureApp(Session session, string installDir)
        {
            var envFile = Path.Combine(installDir, ".env");
            var exampleFile = Path.Combine(installDir, ".env.example");
            var venvPython = Path.Combine(installDir, "venv", "Scripts", "python.exe");

            // Create .env from example if it doesn't exist
            if (!File.Exists(envFile) && File.Exists(exampleFile))
            {
                ProcessRunner.UpdateStatus(session, "Creating configuration file...");
                string content = File.ReadAllText(exampleFile);

                // Generate a random secret key
                string secretKey = Guid.NewGuid().ToString("N") + Guid.NewGuid().ToString("N");
                content = content.Replace(
                    "your-secret-key-here-change-in-production", secretKey);

                File.WriteAllText(envFile, content);
                session.Log(".env created.");
            }

            // Run migrations
            if (File.Exists(venvPython))
            {
                ProcessRunner.UpdateStatus(session, "Running database migrations...");
                string migrationCmd =
                    "from app import create_app, db; " +
                    "from app.migrations import run_migrations; " +
                    "app = create_app(); " +
                    "app.app_context().push(); " +
                    "run_migrations(db)";
                ProcessRunner.Run(session, venvPython,
                    $"-c \"{migrationCmd}\"",
                    workingDirectory: installDir);
                session.Log("Migrations complete.");
            }
        }

        /// <summary>
        /// Create Start Menu and/or desktop shortcuts.
        /// </summary>
        private static void CreateShortcuts(Session session, string installDir,
            bool startMenu, bool desktop)
        {
            int port = GetPortFromEnv(installDir);
            string appUrl = $"http://localhost:{port}";

            // Find icon - prefer MSI-installed copy, fall back to repo
            string iconPath = Path.Combine(installDir, "icon.ico");
            if (!File.Exists(iconPath))
                iconPath = Path.Combine(installDir, "static", "icon.ico");

            if (startMenu)
            {
                var startMenuFolder = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "Microsoft", "Windows", "Start Menu", "Programs", "Sales Buddy");

                if (!Directory.Exists(startMenuFolder))
                    Directory.CreateDirectory(startMenuFolder);

                // Main app shortcut
                CreateShortcutLink(
                    Path.Combine(startMenuFolder, $"{AppName}.lnk"),
                    "explorer.exe", appUrl, "",
                    File.Exists(iconPath) ? $"{iconPath},0" : "",
                    "Open Sales Buddy in your browser");

                // Start Server
                CreateShortcutLink(
                    Path.Combine(startMenuFolder, "Start Server.lnk"),
                    Path.Combine(installDir, "start.bat"), "",
                    installDir,
                    File.Exists(iconPath) ? $"{iconPath},0" : "",
                    "Start the Sales Buddy server");

                // Stop Server
                CreateShortcutLink(
                    Path.Combine(startMenuFolder, "Stop Server.lnk"),
                    Path.Combine(installDir, "stop.bat"), "",
                    installDir, "",
                    "Stop the Sales Buddy server");

                // Update
                CreateShortcutLink(
                    Path.Combine(startMenuFolder, "Update.lnk"),
                    Path.Combine(installDir, "update.bat"), "",
                    installDir,
                    File.Exists(iconPath) ? $"{iconPath},0" : "",
                    "Update Sales Buddy to the latest version");

                session.Log("Start Menu shortcuts created.");
            }

            if (desktop)
            {
                var desktopPath = Environment.GetFolderPath(
                    Environment.SpecialFolder.DesktopDirectory);
                CreateShortcutLink(
                    Path.Combine(desktopPath, $"{AppName}.lnk"),
                    "explorer.exe", appUrl, "",
                    File.Exists(iconPath) ? $"{iconPath},0" : "",
                    "Open Sales Buddy in your browser");
                session.Log("Desktop shortcut created.");
            }
        }

        /// <summary>
        /// Register a Windows Task Scheduler task to start the server on login.
        /// </summary>
        private static void ConfigureAutoStartTask(Session session, string installDir)
        {
            string startBat = Path.Combine(installDir, "start.bat");
            if (!File.Exists(startBat))
            {
                session.Log("start.bat not found, skipping auto-start configuration.");
                return;
            }

            // Use schtasks to create a logon trigger task
            ProcessRunner.Run(session, "schtasks.exe",
                $"/create /tn \"SalesBuddy-AutoStart\" " +
                $"/tr \"\\\"{startBat}\\\"\" " +
                $"/sc ONLOGON /rl LIMITED /f");
            session.Log("Auto-start task created.");
        }

        /// <summary>
        /// Start the Sales Buddy server in the background using waitress.
        /// </summary>
        private static void StartServer(Session session, string installDir)
        {
            int port = GetPortFromEnv(installDir);
            var waitress = Path.Combine(installDir, "venv", "Scripts",
                "waitress-serve.exe");

            if (!File.Exists(waitress))
            {
                session.Log("waitress-serve.exe not found. Server not started.");
                return;
            }

            var psi = new ProcessStartInfo
            {
                FileName = waitress,
                Arguments = $"--host=0.0.0.0 --port={port} --call app:create_app",
                WorkingDirectory = installDir,
                UseShellExecute = false,
                CreateNoWindow = true,
            };

            Process.Start(psi);
            session.Log($"Server started on port {port}.");
        }

        // =====================================================================
        // Uninstall helpers
        // =====================================================================

        /// <summary>
        /// Stop the Sales Buddy server by killing waitress processes.
        /// </summary>
        private static void StopServer(Session session, string installDir)
        {
            foreach (var proc in Process.GetProcessesByName("waitress-serve"))
            {
                try
                {
                    proc.Kill();
                    session.Log($"Killed waitress-serve process {proc.Id}.");
                }
                catch (Exception ex)
                {
                    session.Log($"Could not kill process {proc.Id}: {ex.Message}");
                }
            }
        }

        /// <summary>
        /// Remove Sales Buddy scheduled tasks.
        /// </summary>
        private static void RemoveScheduledTasks(Session session)
        {
            var taskNames = new[] { "SalesBuddy-AutoStart", "SalesBuddy-DailyBackup" };
            foreach (var taskName in taskNames)
            {
                ProcessRunner.Run(session, "schtasks.exe",
                    $"/delete /tn \"{taskName}\" /f");
            }
        }

        /// <summary>
        /// Remove Start Menu and desktop shortcuts.
        /// </summary>
        private static void RemoveShortcuts(Session session)
        {
            var startMenuFolder = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "Microsoft", "Windows", "Start Menu", "Programs", "Sales Buddy");

            if (Directory.Exists(startMenuFolder))
            {
                Directory.Delete(startMenuFolder, true);
                session.Log("Start Menu shortcuts removed.");
            }

            var desktopShortcut = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                $"{AppName}.lnk");

            if (File.Exists(desktopShortcut))
            {
                File.Delete(desktopShortcut);
                session.Log("Desktop shortcut removed.");
            }
        }

        // =====================================================================
        // Utilities
        // =====================================================================

        /// <summary>
        /// Install a package via winget with retry logic for MSI mutex conflicts.
        /// </summary>
        private static void InstallViaWinget(Session session, string name,
            string packageId, string testCommand)
        {
            const int maxAttempts = 3;
            for (int attempt = 1; attempt <= maxAttempts; attempt++)
            {
                int exitCode = ProcessRunner.Run(session, "winget",
                    $"install {packageId} --silent " +
                    "--accept-package-agreements --accept-source-agreements");

                if (exitCode == 0)
                {
                    PathHelper.RefreshPath();
                    session.Log($"{name} installed successfully.");
                    return;
                }

                // Exit code -1978335189 means "already installed"
                if (exitCode == -1978335189 || exitCode == unchecked((int)0x8A150019))
                {
                    PathHelper.RefreshPath();
                    session.Log($"{name} already installed (winget confirmed).");
                    return;
                }

                // Exit code -1978334974 wraps MSI error 1618 (mutex conflict).
                // Wait and retry. Use Thread.Sleep since we're in a deferred CA.
                if ((exitCode == -1978334974 || exitCode == unchecked((int)0x8A150022))
                    && attempt < maxAttempts)
                {
                    session.Log($"{name} install hit MSI mutex. " +
                        $"Waiting 15s before retry ({attempt}/{maxAttempts})...");
                    ProcessRunner.UpdateStatus(session,
                        $"Waiting for another installer to finish ({attempt}/{maxAttempts})...");
                    System.Threading.Thread.Sleep(15000);
                    continue;
                }

                session.Log($"Failed to install {name} (exit code: {exitCode}).");
                return;
            }
        }

        /// <summary>
        /// Download a file from a URL.
        /// </summary>
        private static void DownloadFile(Session session, string url, string destPath)
        {
            session.Log($"Downloading {url}");
            using (var client = new WebClient())
            {
                client.DownloadFile(url, destPath);
            }
            session.Log($"Downloaded to {destPath}");
        }

        /// <summary>
        /// Read the PORT setting from the app's .env file.
        /// </summary>
        private static int GetPortFromEnv(string installDir)
        {
            var envFile = Path.Combine(installDir, ".env");
            if (File.Exists(envFile))
            {
                foreach (var line in File.ReadAllLines(envFile))
                {
                    var match = Regex.Match(line, @"^\s*PORT\s*=\s*(\d+)");
                    if (match.Success)
                        return int.Parse(match.Groups[1].Value);
                }
            }
            return DefaultPort;
        }

        /// <summary>
        /// Read a boolean value from CustomActionData.
        /// Returns true if the key exists and its value is "1".
        /// </summary>
        private static bool GetBoolData(CustomActionData data, string key)
        {
            return data.ContainsKey(key) && !string.IsNullOrEmpty(data[key])
                && data[key] != "0";
        }

        /// <summary>
        /// Prepend locally-installed tool directories to the process PATH
        /// so they take priority over Windows Store stubs.
        /// </summary>
        private static void PrependLocalTools()
        {
            var localAppData = Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData);
            var dirs = new[]
            {
                Path.Combine(localAppData, "python"),
                Path.Combine(localAppData, "python", "Scripts"),
                Path.Combine(localAppData, "nodejs"),
            };
            foreach (var dir in dirs)
            {
                if (Directory.Exists(dir))
                    PathHelper.AddToPath(dir);
            }
        }

        /// <summary>
        /// Create a Windows shortcut (.lnk) using the WScript.Shell COM object.
        /// </summary>
        private static void CreateShortcutLink(string shortcutPath, string targetPath,
            string arguments, string workingDirectory, string iconLocation,
            string description)
        {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            dynamic shell = Activator.CreateInstance(shellType);
            try
            {
                dynamic shortcut = shell.CreateShortcut(shortcutPath);
                try
                {
                    shortcut.TargetPath = targetPath;
                    if (!string.IsNullOrEmpty(arguments))
                        shortcut.Arguments = arguments;
                    if (!string.IsNullOrEmpty(workingDirectory))
                        shortcut.WorkingDirectory = workingDirectory;
                    if (!string.IsNullOrEmpty(iconLocation))
                        shortcut.IconLocation = iconLocation;
                    if (!string.IsNullOrEmpty(description))
                        shortcut.Description = description;
                    shortcut.Save();
                }
                finally
                {
                    Marshal.ReleaseComObject(shortcut);
                }
            }
            finally
            {
                Marshal.ReleaseComObject(shell);
            }
        }

        /// <summary>
        /// Clean up temporary download and extraction files.
        /// </summary>
        private static void CleanupTemp(string zipPath, string extractDir)
        {
            try { if (File.Exists(zipPath)) File.Delete(zipPath); }
            catch { /* best effort */ }
            try { if (Directory.Exists(extractDir)) Directory.Delete(extractDir, true); }
            catch { /* best effort */ }
        }
    }
}
