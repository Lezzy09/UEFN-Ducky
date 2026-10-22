using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Threading;
using System.Threading.Tasks;

namespace DuckySetup
{
    // The uninstaller's window (ui/uninstall.html): why are you leaving, keep or delete
    // your data, then Inno's uninstaller runs silently behind a progress bar.
    internal sealed class UninstallForm : DuckyWindow
    {
        Uninstall.Target? _target;
        bool _running;
        bool _done;
        bool _reported;
        bool _answered;
        bool _deleteData;
        string _reason = "none";
        string _code = "ok";

        public UninstallForm() : base("Uninstall UEFN Ducky", "uninstall.html")
        {
        }

        protected override void HandleMessage(string type, Dictionary<string, object> msg)
        {
            if (type == "ready")
            {
                PostInit();
                return;
            }
            if (type == "uninstall")
            {
                Start(msg);
                return;
            }
            // Keep UEFN Ducky, or the window closed before uninstalling: they stayed.
            if (type == "keep" || type == "quit" || type == "finish")
            {
                if (_running)
                    return; // Inno's uninstaller can't be stopped part way
                if (!_done && _target != null)
                {
                    if (type != "finish")
                        Answer(msg);
                    Report("cancel");
                }
                Close();
            }
        }

        void PostInit()
        {
            Usage.Load(persist: false);
            _target = Uninstall.Find();
            Post(new
            {
                type = "init",
                installed = _target != null,
                version = _target?.Version ?? "",
            });
        }

        void Answer(Dictionary<string, object> msg)
        {
            _reason = Stats.Reason(Str(msg, "reason"));
            var text = Str(msg, "text");
            Usage.Feedback(text);
            _answered = _reason != "none" || Stats.CleanText(text).Length > 0;
            _deleteData = Truthy(msg, "deleteData");
        }

        void Start(Dictionary<string, object> msg)
        {
            if (_running || _done || _target == null)
                return;
            Answer(msg);
            _reported = false;
            _running = true;
            var target = _target;
            Task.Run(() => Work(target)).ContinueWith(t =>
            {
                var (ok, error) = t.IsFaulted
                    ? (false, "The uninstall didn't finish: " + (t.Exception?.GetBaseException().Message ?? "unknown error"))
                    : t.Result;
                OnUi(() => Finished(ok, error));
            });
        }

        (bool ok, string error) Work(Uninstall.Target t)
        {
            Progress(0, "Closing UEFN Ducky…");
            var total = Uninstall.CountFiles(t.Dir);
            System.Diagnostics.Process proc;
            try
            {
                proc = Uninstall.Start(t);
            }
            catch (Win32Exception ex) when (ex.NativeErrorCode == 1223)
            {
                _code = "uac_declined";
                return (false, "Windows asked for permission and it wasn't given, so UEFN Ducky is still installed.");
            }
            catch (Exception ex) when (ex is Win32Exception || ex is InvalidOperationException)
            {
                _code = "start_failed";
                return (false, "The uninstaller couldn't start: " + ex.Message);
            }
            int code;
            using (proc)
            {
                while (!proc.WaitForExit(400))
                    Removed(t, total);
                code = proc.ExitCode;
            }
            // Gone means the app's EXE and the uninstall entry; give a slow disk two minutes.
            var until = DateTime.UtcNow.AddMinutes(2);
            while (Uninstall.StillInstalled(t) && DateTime.UtcNow < until)
            {
                Removed(t, total);
                Thread.Sleep(500);
            }
            if (Uninstall.StillInstalled(t))
            {
                _code = code == 0 ? "still_installed" : Stats.ExitCode(code);
                return (false, code == 0
                    ? "UEFN Ducky is still installed. Close it and try again."
                    : "The uninstall didn't finish. If Windows asked for permission, choose Yes and try again.");
            }
            Uninstall.Tidy(t);
            if (_deleteData)
            {
                Progress(94, "Deleting your chats and settings…");
                Uninstall.DeleteData();
            }
            _code = "ok";
            return (true, "");
        }

        // The install folder empties as Inno works: that is the bar (to 90%).
        void Removed(Uninstall.Target t, int total)
        {
            var left = Uninstall.CountFiles(t.Dir);
            if (total <= 0 || left < 0)
                return;
            var percent = (int)Math.Round(90.0 * (total - Math.Min(total, left)) / total);
            Progress(percent, "Removing UEFN Ducky…");
        }

        void Progress(int percent, string status)
        {
            OnUi(() => Post(new { type = "progress", percent, status }));
        }

        void Finished(bool ok, string error)
        {
            _running = false;
            _done = ok;
            Report(ok ? "ok" : "fail");
            // The id goes with the data, so a later install counts as a new PC.
            if (ok && _deleteData)
                Usage.Forget();
            Post(new { type = "done", ok, error, deleted = ok && _deleteData });
        }

        // Once per try: how it ended, why they left, and (from Since) how long they had it.
        void Report(string outcome)
        {
            if (_reported)
                return;
            _reported = true;
            var age = Usage.Since < 0 ? -1 : DateTimeOffset.UtcNow.ToUnixTimeSeconds() - Usage.Since;
            Usage.Track("uninstall.done", new Dictionary<string, string>
            {
                ["outcome"] = outcome,
                ["reason"] = _reason,
                ["data"] = _deleteData ? "delete" : "keep",
                ["age"] = Stats.AgeBucket(age),
                ["code"] = outcome == "cancel" ? "cancelled" : _code,
            }, always: _answered);
            Usage.SendNow(3000);
        }

        protected override void OnFormClosing(System.Windows.Forms.FormClosingEventArgs e)
        {
            // Alt+F4 while Inno works: the uninstall goes on, so the window stays.
            if (_running)
            {
                e.Cancel = true;
                return;
            }
            base.OnFormClosing(e);
        }
    }
}
