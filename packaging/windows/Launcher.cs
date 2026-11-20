using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
class Launcher {
    [STAThread] static int Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, "Runtime", "python.exe");
        string entry = Path.Combine(root, "App", "windows_entry.py");
        string log = Path.Combine(root, "Logs", "launcher.log");
        try {
            if (!File.Exists(python) || !File.Exists(entry))
                throw new Exception("Incomplete bundle: Runtime/python.exe or App/windows_entry.py is missing.");
            Directory.CreateDirectory(Path.GetDirectoryName(log));
            using (StreamWriter writer = new StreamWriter(log, true)) {
                writer.AutoFlush = true;
                writer.WriteLine("\nStartup " + DateTime.Now.ToString("s"));
                Process p = new Process();
                p.StartInfo = new ProcessStartInfo(python, "-u \"" + entry + "\"");
                p.StartInfo.WorkingDirectory = Path.Combine(root, "App");
                p.StartInfo.UseShellExecute = false;
                p.StartInfo.CreateNoWindow = true;
                p.StartInfo.EnvironmentVariables["PYTHONUTF8"] = "1";
                p.StartInfo.StandardOutputEncoding = System.Text.Encoding.UTF8;
                p.StartInfo.StandardErrorEncoding = System.Text.Encoding.UTF8;
                p.StartInfo.RedirectStandardOutput = true;
                p.StartInfo.RedirectStandardError = true;
                p.OutputDataReceived += (s,e) => { if (e.Data != null) lock(writer) { writer.WriteLine(e.Data); } };
                p.ErrorDataReceived += (s,e) => { if (e.Data != null) lock(writer) { writer.WriteLine(e.Data); } };
                p.Start(); p.BeginOutputReadLine(); p.BeginErrorReadLine(); p.WaitForExit();
                if (p.ExitCode != 0) MessageBox.Show("BUTUZIK.AI could not start. See:\n" + log,
                    "BUTUZIK.AI", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return p.ExitCode;
            }
        } catch (Exception e) {
            MessageBox.Show(e.Message + "\n\nExtract the complete folder into a writable local directory.",
                "BUTUZIK.AI", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
