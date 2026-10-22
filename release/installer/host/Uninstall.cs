using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;

namespace DuckySetup
{
    // UEFN Ducky's own uninstaller: this same host, installed beside the app as
    // "Uninstall UEFN Ducky.exe", which Apps & features opens. It asks why, runs Inno's
    // uninstaller (unins000.exe) silently while it shows the progress, and deletes the
    // person's data when they ask. It first copies itself to %TEMP% and runs from there,
    // so the install folder it starts in can be removed.
    internal static class Uninstall
    {
        public const string ExeName = "Uninstall UEFN Ducky.exe";
        public const string Switch = "/UNINSTALL";
        const string FromTempSwitch = "/FROMTEMP";
        const string TempPrefix = "UEFN-Ducky-Uninstall-";

        // The installed copy: Inno's uninstaller and the folder it empties.
        internal sealed class Target
        {
            public string Dir = "";
            public string Uninstaller = "";
            public string Version = "";
        }

        public static bool Requested(string[] args) =>
            args.Any(a => a.Equals(Switch, StringComparison.OrdinalIgnoreCase))
            || Path.GetFileName(Application.ExecutablePath).IndexOf("uninstall", StringComparison.OrdinalIgnoreCase) >= 0;

        public static bool FromTemp(string[] args) =>
            args.Any(a => a.Equals(FromTempSwitch, StringComparison.OrdinalIgnoreCase));

        // Copies this EXE into its own temp folder and starts that copy.
        public static int Relaunch(string[] args)
        {
            try
            {
                SweepOld();
                var dir = Path.Combine(Path.GetTempPath(), TempPrefix + Process.GetCurrentProcess().Id);
                Directory.CreateDirectory(dir);
                var copy = Path.Combine(dir, ExeName);
                File.Copy(Application.ExecutablePath, copy, true);
                var rest = args.Where(a => !a.Equals(Switch, StringComparison.OrdinalIgnoreCase)
                    && !a.Equals(FromTempSwitch, StringComparison.OrdinalIgnoreCase));
                Process.Start(new ProcessStartInfo
                {
                    FileName = copy,
                    Arguments = HostArgs.Join(new[] { Switch, FromTempSwitch }.Concat(rest)),
                    UseShellExecute = false,
                    WorkingDirectory = dir,
                })?.Dispose();
                return 0;
            }
            catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException || ex is Win32Exception)
            {
                Engine.LogHostError(ex);
                MessageBox.Show(
                    "UEFN Ducky's uninstaller couldn't start.\n\n" + ex.Message,
                    "Uninstall UEFN Ducky",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                return 1;
            }
        }

        // Earlier runs' temp folders (each keeps its EXE and WebView2 profile until the next run).
        static void SweepOld()
        {
            try
            {
                foreach (var dir in Directory.GetDirectories(Path.GetTempPath(), TempPrefix + "*"))
                {
                    try { Directory.Delete(dir, true); }
                    catch (Exception) { /* that window is still open */ }
                }
            }
            catch (Exception)
            {
                // no temp folder listing: nothing to sweep
            }
        }

        public static Target? Find()
        {
            var (installed, _, location) = Engine.DetectInstall();
            if (!installed || string.IsNullOrEmpty(location))
                return null;
            var uninstaller = InnoUninstaller(location!);
            if (uninstaller == null)
                return null;
            return new Target { Dir = location!, Uninstaller = uninstaller, Version = Engine.InstalledVersion() };
        }

        // Inno's own uninstaller: the quiet uninstall command names it ("…\unins000.exe"
        // /SILENT); without one, the last unins###.exe in the install folder.
        static string? InnoUninstaller(string dir)
        {
            var exe = Stats.ExePath(Engine.UninstallValue("QuietUninstallString"));
            if (exe.Length > 0 && File.Exists(exe) && Path.GetFileName(exe).StartsWith("unins", StringComparison.OrdinalIgnoreCase))
                return exe;
            try
            {
                return Directory.GetFiles(dir, "unins*.exe").OrderBy(f => f, StringComparer.OrdinalIgnoreCase).LastOrDefault();
            }
            catch (Exception)
            {
                return null;
            }
        }

        // Inno's uninstaller closes UEFN Ducky first and, for an install for everyone,
        // asks Windows for permission itself. Its first copy waits for the one it runs
        // from %TEMP%, so this process ends when the uninstall does.
        public static Process Start(Target t, string arguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART")
        {
            return Process.Start(new ProcessStartInfo
            {
                FileName = t.Uninstaller,
                Arguments = arguments,
                UseShellExecute = true,
                WorkingDirectory = Path.GetTempPath(),
            }) ?? throw new InvalidOperationException("Couldn't start the uninstaller.");
        }

        public static bool StillInstalled(Target t) =>
            File.Exists(Path.Combine(t.Dir, Engine.AppExeName)) || Engine.DetectInstall().installed;

        // Files left in the install folder (-1 while it can't be listed).
        public static int CountFiles(string dir)
        {
            try
            {
                return Directory.Exists(dir) ? Directory.EnumerateFiles(dir, "*", SearchOption.AllDirectories).Count() : 0;
            }
            catch (Exception)
            {
                return -1;
            }
        }

        // What Inno doesn't know it installed: this uninstaller when the app put it there.
        public static void Tidy(Target t)
        {
            try { File.Delete(Path.Combine(t.Dir, ExeName)); }
            catch (Exception) { /* not there */ }
            try
            {
                if (Directory.Exists(t.Dir) && !Directory.EnumerateFileSystemEntries(t.Dir).Any())
                    Directory.Delete(t.Dir);
            }
            catch (Exception)
            {
                // something else lives there now
            }
        }

        // "Also delete my data": this Windows user's chats, settings and project data.
        // False when some files stayed (still in use).
        public static bool DeleteData()
        {
            var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var ok = true;
            // UEFN-Agent: the folder of the old brand's builds.
            foreach (var name in new[] { "UEFN-Ducky", "UEFN-Agent" })
            {
                var dir = Path.Combine(local, name);
                if (Directory.Exists(dir))
                    ok &= DeleteTree(dir);
            }
            return ok;
        }

        // File by file, past read-only files and ones still in use. A link (junction or
        // symlink) is removed itself; what it points at is never entered.
        static bool DeleteTree(string dir)
        {
            var ok = true;
            try
            {
                foreach (var entry in new DirectoryInfo(dir).EnumerateFileSystemInfos().ToList())
                {
                    if (entry is DirectoryInfo sub && (sub.Attributes & FileAttributes.ReparsePoint) == 0)
                    {
                        ok &= DeleteTree(sub.FullName);
                        continue;
                    }
                    try
                    {
                        entry.Attributes = FileAttributes.Normal;
                        entry.Delete();
                    }
                    catch (Exception)
                    {
                        ok = false;
                    }
                }
                Directory.Delete(dir);
            }
            catch (Exception)
            {
                ok = false;
            }
            return ok;
        }

        // /SILENT or /VERYSILENT: no window and no question, Inno's uninstaller with those switches.
        public static int RunSilent(string[] args)
        {
            var t = Find();
            if (t == null)
                return 0;
            var pass = args.Where(a => !a.Equals(Switch, StringComparison.OrdinalIgnoreCase)
                && !a.Equals(FromTempSwitch, StringComparison.OrdinalIgnoreCase));
            try
            {
                using var proc = Start(t, HostArgs.Join(pass));
                proc.WaitForExit();
                var code = proc.ExitCode;
                if (code == 0)
                    Tidy(t);
                return code;
            }
            catch (Exception ex)
            {
                Engine.LogHostError(ex);
                return 1;
            }
        }
    }
}
