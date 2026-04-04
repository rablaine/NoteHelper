using System;
using System.Diagnostics;
using System.Text;
using WixToolset.Dtf.WindowsInstaller;

namespace SalesBuddy.CustomActions
{
    /// <summary>
    /// Runs external commands with output capture and MSI UI status updates.
    /// All commands run with CreateNoWindow=true so no terminal windows appear.
    /// </summary>
    public static class ProcessRunner
    {
        /// <summary>
        /// Run a command, capture output, and optionally update MSI status text
        /// with each stdout line.
        /// </summary>
        /// <param name="session">MSI session for logging and UI updates.</param>
        /// <param name="fileName">Executable to run.</param>
        /// <param name="arguments">Command-line arguments.</param>
        /// <param name="statusPrefix">If set, each stdout line updates the MSI status
        /// text as "{statusPrefix}{line}". Use null to skip UI updates.</param>
        /// <param name="workingDirectory">Working directory for the process.</param>
        /// <returns>Process exit code.</returns>
        public static int Run(
            Session session,
            string fileName,
            string arguments,
            string statusPrefix = null,
            string workingDirectory = null)
        {
            var psi = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };

            if (!string.IsNullOrEmpty(workingDirectory))
                psi.WorkingDirectory = workingDirectory;

            session.Log($"[CMD] {fileName} {arguments}");

            using (var process = Process.Start(psi))
            {
                // Read stderr asynchronously to prevent deadlock when both
                // stdout and stderr buffers fill simultaneously.
                var stderr = new StringBuilder();
                process.ErrorDataReceived += (sender, e) =>
                {
                    if (e.Data != null) stderr.AppendLine(e.Data);
                };
                process.BeginErrorReadLine();

                while (!process.StandardOutput.EndOfStream)
                {
                    var line = process.StandardOutput.ReadLine();
                    if (string.IsNullOrWhiteSpace(line)) continue;

                    session.Log(line);
                    if (statusPrefix != null)
                    {
                        UpdateStatus(session, $"{statusPrefix}{line}");
                    }
                }

                process.WaitForExit();

                if (stderr.Length > 0)
                    session.Log($"[STDERR] {stderr}");

                session.Log($"[EXIT] {process.ExitCode}");
                return process.ExitCode;
            }
        }

        /// <summary>
        /// Run a PowerShell script block without showing a terminal window.
        /// Writes the script to a temp file and executes it with -File.
        /// </summary>
        /// <param name="session">MSI session for logging and UI updates.</param>
        /// <param name="script">PowerShell script content.</param>
        /// <param name="statusPrefix">If set, stdout lines update the MSI status text.</param>
        /// <returns>Process exit code.</returns>
        public static int RunPowerShell(
            Session session,
            string script,
            string statusPrefix = null)
        {
            var tempScript = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(),
                $"SalesBuddy-{Guid.NewGuid():N}.ps1");

            System.IO.File.WriteAllText(tempScript, script);
            try
            {
                return Run(session, "powershell.exe",
                    $"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{tempScript}\"",
                    statusPrefix);
            }
            finally
            {
                try { System.IO.File.Delete(tempScript); }
                catch { /* best effort cleanup */ }
            }
        }

        /// <summary>
        /// Update the status text on the MSI progress page.
        /// </summary>
        public static void UpdateStatus(Session session, string message)
        {
            using (var record = new Record(1))
            {
                record[1] = message;
                session.Message(InstallMessage.ActionData, record);
            }
        }
    }
}
