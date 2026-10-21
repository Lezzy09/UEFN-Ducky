using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace DuckySetup
{
    internal sealed class InstallerForm : Form
    {
        readonly WebView2 _web = new WebView2 { Dock = DockStyle.Fill };
        readonly JavaScriptSerializer _json = new JavaScriptSerializer();
        readonly string _version;
        ProcessHandle? _running;
        System.Windows.Forms.Timer? _poll;
        string _installDir = Engine.UserDir;
        // Web installer only: the Store's latest release, the download's cancel switch,
        // and the downloaded full Setup (deleted once it installed).
        readonly bool _isWeb = Web.IsWeb;
        Task<StoreRelease>? _release;
        System.Threading.CancellationTokenSource? _download;
        string? _downloaded;

        sealed class ProcessHandle
        {
            public System.Diagnostics.Process Proc = null!;
        }

        // Logical size; scaled to the monitor's DPI so the page never gets cramped.
        static readonly Size BaseSize = new Size(720, 500);

        public InstallerForm(string version)
        {
            _version = version;
            Text = "UEFN Ducky Setup";
            FormBorderStyle = FormBorderStyle.None;
            MaximizeBox = false; // the page drags the window; a double-click must not maximize it
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = BaseSize;
            BackColor = Color.FromArgb(10, 10, 10);
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); }
            catch (Exception) { /* keep the default taskbar icon */ }
            Controls.Add(_web);
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            // No title bar, no border: round the corners and drop DWM's 1px
            // outline (Windows 11; both calls are no-ops on Windows 10).
            var round = Native.DwmwcpRound;
            Native.DwmSetWindowAttribute(Handle, Native.DwmwaWindowCornerPreference, ref round, sizeof(int));
            var none = Native.DwmwaColorNone;
            Native.DwmSetWindowAttribute(Handle, Native.DwmwaBorderColor, ref none, sizeof(int));
        }

        protected override void OnDpiChanged(DpiChangedEventArgs e)
        {
            base.OnDpiChanged(e);
            Bounds = e.SuggestedRectangle;
        }

        protected override CreateParams CreateParams
        {
            get
            {
                var cp = base.CreateParams;
                cp.ClassStyle |= 0x00020000; // CS_DROPSHADOW
                return cp;
            }
        }

        protected override async void OnLoad(EventArgs e)
        {
            base.OnLoad(e);
            // Ask the Store which version this installs while the page loads.
            if (_isWeb)
                _release = Task.Run(Web.FetchLatest);
            var scale = DeviceDpi / 96f;
            if (scale > 1.01f)
            {
                ClientSize = new Size((int)Math.Round(BaseSize.Width * scale), (int)Math.Round(BaseSize.Height * scale));
                CenterToScreen();
            }
            try
            {
                await InitWeb();
            }
            catch (Exception ex)
            {
                var text = ex.ToString();
                try
                {
                    Directory.CreateDirectory(Engine.AppDataRoot);
                    File.WriteAllText(Path.Combine(Engine.AppDataRoot, "setup-host.log"), text);
                }
                catch { /* ignore */ }
                MessageBox.Show(
                    this,
                    "UEFN Ducky Setup could not start the installer window.\n\n" + ex.Message,
                    "UEFN Ducky Setup",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
                Environment.ExitCode = 1;
                Close();
            }
        }

        async Task InitWeb()
        {
            Engine.ExtractUi();
            var env = await CoreWebView2Environment.CreateAsync(
                null,
                Path.Combine(Engine.AppDataRoot, "setup-webview-" + System.Diagnostics.Process.GetCurrentProcess().Id));
            await _web.EnsureCoreWebView2Async(env);
            _web.DefaultBackgroundColor = Color.FromArgb(255, 10, 10, 10);
            _web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            _web.CoreWebView2.Settings.AreDevToolsEnabled = false;
            _web.CoreWebView2.Settings.IsStatusBarEnabled = false;
            _web.CoreWebView2.WebMessageReceived += OnMessage;
            _web.CoreWebView2.SetVirtualHostNameToFolderMapping(
                "ducky.setup",
                Engine.UiDir,
                CoreWebView2HostResourceAccessKind.Allow);
            _web.CoreWebView2.Navigate("https://ducky.setup/index.html");
        }

        void OnMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            Dictionary<string, object> msg;
            try { msg = _json.Deserialize<Dictionary<string, object>>(e.WebMessageAsJson); }
            catch { return; }
            var type = Str(msg, "type");
            if (type == "ready") { PostInit(); return; }
            if (type == "drag")
            {
                Native.ReleaseCapture();
                Native.SendMessage(Handle, Native.WmNcLButtonDown, Native.HtCaption, 0);
                return;
            }
            if (type == "minimize") { WindowState = FormWindowState.Minimized; return; }
            if (type == "quit")
            {
                CancelRun();
                Close();
                return;
            }
            if (type == "pickFolder") { PickFolder(Str(msg, "path")); return; }
            if (type == "diskFree") { PostDisk(Str(msg, "path")); return; }
            if (type == "startInstall") { StartInstall(msg); return; }
            if (type == "cancel") { CancelRun(); return; }
            if (type == "finish")
            {
                if (Truthy(msg, "launch"))
                    Engine.LaunchApp(_installDir);
                Close();
            }
        }

        async void PostInit()
        {
            var detect = Engine.DetectInstall();
            _installDir = detect.location ?? Engine.UserDir;
            // The web installer installs whatever the Store has now; no version shows
            // when the Store can't be reached yet (Install then says why).
            var version = _version;
            if (_isWeb)
            {
                try { version = (await _release!).Version; }
                catch (Exception) { version = ""; }
            }
            Post(new
            {
                type = "init",
                version,
                previousVersion = detect.installed ? Engine.InstalledVersion() : "",
                license = Embed.ReadText("LICENSE"),
                isUpgrade = detect.installed,
                allUsers = detect.allUsers,
                dir = _installDir,
                userDir = Engine.UserDir,
                machineDir = Engine.MachineDir,
            });
            PostDisk(_installDir);
        }

        void PickFolder(string current)
        {
            using var dlg = new FolderBrowserDialog
            {
                Description = "Where should UEFN Ducky be installed?",
                SelectedPath = Directory.Exists(current) ? current : Engine.UserDir,
                ShowNewFolderButton = true,
            };
            if (dlg.ShowDialog(this) == DialogResult.OK)
                Post(new { type = "folderPicked", path = dlg.SelectedPath });
        }

        void PostDisk(string path)
        {
            var info = Engine.DiskFree(path);
            if (info == null)
            {
                Post(new { type = "diskFree", text = "", low = false });
                return;
            }
            // The installed app is about 400 MB; the web installer also keeps its download until done.
            var needMb = _isWeb ? 650UL : 450UL;
            var low = info.Value.free < needMb * 1024 * 1024;
            var text = Engine.FormatBytes(info.Value.free) + " free on this drive";
            if (low) text += " — Setup needs about " + needMb + " MB";
            Post(new { type = "diskFree", text, low });
        }

        void StartInstall(Dictionary<string, object> msg)
        {
            var dir = Str(msg, "dir");
            if (dir.Length == 0) dir = Engine.UserDir;
            _installDir = dir;
            var allUsers = Truthy(msg, "allUsers");
            var desktop = Truthy(msg, "desktopIcon");
            var isUpgrade = Truthy(msg, "isUpgrade");
            Engine.ClearProgress();
            var args = Engine.InteractiveArgs(
                isUpgrade ? "" : dir,
                allUsers,
                desktop,
                nolaunch: true,
                setTasks: !isUpgrade);
            if (_isWeb)
            {
                StartWebInstall(args);
                return;
            }
            System.Diagnostics.Process proc;
            string path;
            try
            {
                path = Engine.ExtractEngine();
                proc = Engine.Start(path, args);
                _running = new ProcessHandle { Proc = proc };
            }
            catch (Exception ex)
            {
                Post(new { type = "installDone", ok = false, error = ex.Message });
                return;
            }
            _poll = new System.Windows.Forms.Timer { Interval = 250 };
            _poll.Tick += (_, __) => PostProgress();
            _poll.Start();
            // Same wait as the silent path: it follows the elevated engine after
            // UAC Yes, so "Done" never shows while files are still being copied.
            Task.Run(() => Engine.Wait(proc, path)).ContinueWith(t =>
            {
                var code = t.IsFaulted ? 1 : t.Result;
                try { BeginInvoke((Action)(() => FinishInstall(code))); }
                catch (InvalidOperationException) { /* window already closed */ }
            });
        }

        // Web installer: download and check the Store's full Setup, then run it silently
        // with the same switches and show its engine's progress after the download's.
        async void StartWebInstall(string[] args)
        {
            var cancel = new System.Threading.CancellationTokenSource();
            _download = cancel;
            string path;
            try
            {
                Post(new { type = "progress", percent = 0, status = "Connecting to the UEFN Ducky Store…" });
                if (_release == null || _release.IsFaulted || _release.IsCanceled)
                    _release = Task.Run(Web.FetchLatest);
                var release = await _release;
                path = await Task.Run(() => Web.Download(release, (got, total) => OnUi(() =>
                {
                    var status = got >= total ? "Checking the download…" : WebRelease.DownloadStatus(got, total);
                    Post(new { type = "progress", percent = WebRelease.DownloadPercent(got, total), status });
                }), cancel.Token));
            }
            catch (Exception ex)
            {
                _download = null;
                var error = ex is OperationCanceledException || cancel.IsCancellationRequested
                    ? "Setup was cancelled."
                    : ex is InvalidOperationException || ex is UnauthorizedAccessException || ex is IOException
                        ? ex.Message
                        : "Setup couldn't download UEFN Ducky. Check your internet connection and try again.";
                Post(new { type = "installDone", ok = false, error });
                return;
            }
            _download = null;
            if (cancel.IsCancellationRequested)
            {
                Post(new { type = "installDone", ok = false, error = "Setup was cancelled." });
                return;
            }
            _downloaded = path;
            System.Diagnostics.Process proc;
            try
            {
                proc = Web.StartSetup(path, args);
                _running = new ProcessHandle { Proc = proc };
            }
            catch (Exception ex)
            {
                Post(new { type = "installDone", ok = false, error = ex.Message });
                return;
            }
            Post(new { type = "progress", percent = WebRelease.DownloadShare, status = "Installing…" });
            _poll = new System.Windows.Forms.Timer { Interval = 250 };
            _poll.Tick += (_, __) => PostProgress();
            _poll.Start();
            // The downloaded Setup waits for its engine (and the elevated copy after
            // UAC Yes) itself and exits with the engine's exit code.
            _ = Task.Run(() =>
            {
                proc.WaitForExit();
                return proc.ExitCode;
            }).ContinueWith(t => OnUi(() => FinishInstall(t.IsFaulted ? 1 : t.Result)));
        }

        void OnUi(Action action)
        {
            try { BeginInvoke(action); }
            catch (InvalidOperationException) { /* window already closed */ }
        }

        // Stops a download, the downloaded Setup and its engine.
        void CancelRun()
        {
            _download?.Cancel();
            if (_isWeb && _running != null)
            {
                try { if (!_running.Proc.HasExited) _running.Proc.Kill(); }
                catch (Exception) { /* already gone */ }
            }
            Engine.Cancel();
        }

        void PostProgress()
        {
            var progress = Engine.ReadProgress();
            if (progress == null)
                return;
            var percent = _isWeb ? WebRelease.InstallPercent(progress.Value.percent) : progress.Value.percent;
            Post(new { type = "progress", percent, status = progress.Value.status });
        }

        void FinishInstall(int code)
        {
            _poll?.Stop();
            PostProgress();
            _running = null;
            if (code == 0 && _isWeb)
            {
                Web.Cleanup(_downloaded);
                _downloaded = null;
            }
            if (code == 0)
                Post(new { type = "installDone", ok = true });
            else
                Post(new
                {
                    type = "installDone",
                    ok = false,
                    error = "Installer did not finish. If Windows asked for permission, choose Yes and try again.",
                });
        }

        void Post(object payload)
        {
            if (_web.CoreWebView2 == null) return;
            _web.CoreWebView2.PostWebMessageAsJson(_json.Serialize(payload));
        }

        static string Str(Dictionary<string, object> msg, string key)
        {
            return msg.TryGetValue(key, out var v) && v != null ? Convert.ToString(v) ?? "" : "";
        }

        static bool Truthy(Dictionary<string, object> msg, string key)
        {
            if (!msg.TryGetValue(key, out var v) || v == null) return false;
            if (v is bool b) return b;
            var s = Convert.ToString(v);
            return s == "True" || s == "true" || s == "1";
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (_running != null || _download != null)
                CancelRun();
            _poll?.Stop();
            base.OnFormClosing(e);
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            _poll?.Stop();
            base.OnFormClosed(e);
        }
    }
}
