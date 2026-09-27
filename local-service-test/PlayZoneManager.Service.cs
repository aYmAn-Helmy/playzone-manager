using System;
using System.Diagnostics;
using System.IO;
using System.ServiceProcess;
using System.Threading;

namespace PlayZoneManagerService
{
    public sealed class PlayZoneService : ServiceBase
    {
        private Process child;
        private readonly object logLock = new object();
        private bool stopping = false;
        private string installRoot;
        private string runtimeRoot;
        private string dataRoot;
        private string logRoot;
        private string stopFile;

        public PlayZoneService()
        {
            ServiceName = "PlayZoneManager";
            CanStop = true;
            CanShutdown = true;
            AutoLog = true;
        }

        private void Log(string message)
        {
            try
            {
                lock (logLock)
                {
                    Directory.CreateDirectory(logRoot);
                    File.AppendAllText(
                        Path.Combine(logRoot, "service-host.log"),
                        DateTime.UtcNow.ToString("o") + " " + message + Environment.NewLine
                    );
                }
            }
            catch { }
        }

        protected override void OnStart(string[] args)
        {
            stopping = false;
            installRoot = Directory.GetParent(AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar)).FullName;
            runtimeRoot = Path.Combine(installRoot, "runtime");
            dataRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "PlayZone Manager");
            logRoot = Path.Combine(dataRoot, "logs");
            stopFile = Path.Combine(dataRoot, "service.stop");
            Directory.CreateDirectory(dataRoot);
            Directory.CreateDirectory(Path.Combine(dataRoot, "data"));
            Directory.CreateDirectory(logRoot);
            try { if (File.Exists(stopFile)) File.Delete(stopFile); } catch { }

            string python = Path.Combine(runtimeRoot, ".runtime", "python", "python.exe");
            string backend = Path.Combine(runtimeRoot, "backend");
            if (!File.Exists(python))
                throw new FileNotFoundException("Portable Python runtime not found", python);
            if (!Directory.Exists(backend))
                throw new DirectoryNotFoundException("PlayZone backend not found: " + backend);

            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = python;
            psi.Arguments = "-m service_runner";
            psi.WorkingDirectory = backend;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;

            string dbPath = Path.Combine(dataRoot, "data", "playzone.db");
            string queuePath = Path.Combine(dataRoot, "data", "offline-queue.db");
            string voltraPath = Path.Combine(dataRoot, "data", "voltra.json");

            psi.EnvironmentVariables["PLAYZONE_DB_PATH"] = dbPath;
            psi.EnvironmentVariables["PLAYZONE_QUEUE_DB_PATH"] = queuePath;
            psi.EnvironmentVariables["PLAYZONE_SERVICE_STOP_FILE"] = stopFile;
            psi.EnvironmentVariables["PLAYZONE_RUNTIME_MODE"] = "WINDOWS_SERVICE";
            psi.EnvironmentVariables["PLAYZONE_CLOUD_SYNC_ENABLED"] = "0";
            psi.EnvironmentVariables["VOLTRA_DATA_PATH"] = voltraPath;
            psi.EnvironmentVariables["VOLTRA_BASE_URL"] = "http://127.0.0.1:8086";
            psi.EnvironmentVariables["VOLTRA_EMBEDDED"] = "1";
            psi.EnvironmentVariables["VOLTRA_DEMO"] = "0";
            psi.EnvironmentVariables["VOLTRA_TCP_PORT"] = "10086";
            psi.EnvironmentVariables["VOLTRA_HTTP_PORT"] = "8086";
            psi.EnvironmentVariables["VOLTRA_POLL_INTERVAL"] = "10";
            psi.EnvironmentVariables["VOLTRA_RESPONSE_TIMEOUT"] = "3";
            psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";

            child = new Process();
            child.StartInfo = psi;
            child.EnableRaisingEvents = true;
            child.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e)
            {
                if (e.Data != null) Log("PY OUT " + e.Data);
            };
            child.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e)
            {
                if (e.Data != null) Log("PY ERR " + e.Data);
            };
            child.Exited += delegate(object sender, EventArgs e)
            {
                int code = 1;
                try { code = child.ExitCode; } catch { }
                Log("Python runtime exited with code " + code + "; stopping=" + stopping);
                if (!stopping)
                {
                    Environment.Exit(code == 0 ? 1 : code);
                }
            };

            Log("Starting PlayZone Python runtime: " + python);
            if (!child.Start())
                throw new InvalidOperationException("Could not start PlayZone Python runtime");
            child.BeginOutputReadLine();
            child.BeginErrorReadLine();
            Log("PlayZone Python runtime PID=" + child.Id);
        }

        protected override void OnStop()
        {
            stopping = true;
            Log("Service stop requested");
            try
            {
                File.WriteAllText(stopFile, DateTime.UtcNow.ToString("o"));
            }
            catch (Exception ex)
            {
                Log("Could not create graceful stop file: " + ex.Message);
            }

            if (child != null)
            {
                try
                {
                    if (!child.HasExited && !child.WaitForExit(20000))
                    {
                        Log("Graceful stop timeout; terminating Python runtime");
                        child.Kill();
                        child.WaitForExit(5000);
                    }
                }
                catch (Exception ex)
                {
                    Log("Stop warning: " + ex.Message);
                }
            }
            try { if (File.Exists(stopFile)) File.Delete(stopFile); } catch { }
            Log("Service stopped");
        }

        protected override void OnShutdown()
        {
            OnStop();
            base.OnShutdown();
        }

        public static void Main(string[] args)
        {
            ServiceBase.Run(new PlayZoneService());
        }
    }
}
