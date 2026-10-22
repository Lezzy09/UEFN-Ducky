using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Microsoft.Win32;

namespace DuckySetup
{
    // Setup's and the uninstaller's anonymous counts: a few named events with enum
    // values (Stats.cs), sent to the Store's usage route under this PC's random id.
    // The id lives in HKCU\Software\UEFN Ducky, where the app keeps the same id and
    // its usage switch (frontend/usage_stats.py), so Setup, the app and the
    // uninstaller count as one PC. Switched off in the app means nothing is sent.
    // Every call swallows its own errors: counts never stop an install.
    internal static class Usage
    {
        public const string KeyPath = @"Software\UEFN Ducky";
        const string CollectPath = "/api/v1/plugins/uefn-ducky-store/collect/usage";

        static readonly object Lock = new object();
        static readonly List<Dictionary<string, object>> Pending = new List<Dictionary<string, object>>();
        static Dictionary<string, object>? _feedback;
        static Task _sending = Task.CompletedTask;

        public static string Id { get; private set; } = "";
        // The PC had an id before this run: UEFN Ducky was on it before.
        public static bool HadId { get; private set; }
        // The app's "Anonymous usage stats" switch (UsageStats = 0 is off).
        public static bool Enabled { get; private set; } = true;
        // When the id was made (unix seconds), -1 when unknown.
        public static long Since { get; private set; } = -1;

        // Reads this PC's id; without one, makes one and (persist) keeps it for the app.
        public static void Load(bool persist)
        {
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(KeyPath);
                if (key != null)
                {
                    Enabled = !(key.GetValue("UsageStats") is int on && on == 0);
                    Since = long.TryParse(Convert.ToString(key.GetValue("InstallSince")), out var since) ? since : -1;
                    var id = (key.GetValue("InstallId") as string ?? "").Trim().ToLowerInvariant();
                    if (Stats.IsInstallId(id))
                    {
                        Id = id;
                        HadId = true;
                        return;
                    }
                }
            }
            catch (Exception)
            {
                // no key, or not readable: a fresh id below
            }
            var bytes = new byte[16];
            using (var rng = RandomNumberGenerator.Create())
                rng.GetBytes(bytes);
            Id = Stats.NewInstallId(bytes);
            HadId = false;
            Since = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            if (!persist)
                return;
            try
            {
                using var key = Registry.CurrentUser.CreateSubKey(KeyPath);
                key?.SetValue("InstallId", Id, RegistryValueKind.String);
                key?.SetValue("InstallSince", Since.ToString(), RegistryValueKind.String);
            }
            catch (Exception)
            {
                // the app makes its own id then
            }
        }

        // Queues one event; `always` sends it even with the switch off (an answer the
        // person chose to give in the uninstaller).
        public static void Track(string name, IDictionary<string, string> props, bool always = false)
        {
            if (!Enabled && !always)
                return;
            var row = new Dictionary<string, object>
            {
                ["name"] = name,
                ["props"] = new Dictionary<string, string>(props),
                ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
            };
            lock (Lock)
                Pending.Add(row);
        }

        // The uninstaller's written answer, sent with its uninstall.done event.
        public static void Feedback(string text)
        {
            var clean = Stats.CleanText(text);
            lock (Lock)
                _feedback = clean.Length > 0 ? new Dictionary<string, object> { ["text"] = clean } : null;
        }

        // Sends what is queued, one batch at a time, in the background.
        public static Task Send()
        {
            lock (Lock)
            {
                _sending = _sending.ContinueWith(_ => SendPending(), TaskScheduler.Default);
                return _sending;
            }
        }

        // On close: send what is queued, waiting at most `timeoutMs`.
        public static void SendNow(int timeoutMs)
        {
            try { Send().Wait(timeoutMs); }
            catch (Exception) { /* best effort */ }
        }

        // "Also delete my data": the id goes with it, so a later install is a new PC.
        public static void Forget()
        {
            try { Registry.CurrentUser.DeleteSubKeyTree(KeyPath, false); }
            catch (Exception) { /* gone already, or in use */ }
        }

        static void SendPending()
        {
            List<Dictionary<string, object>> rows;
            Dictionary<string, object>? feedback;
            lock (Lock)
            {
                if (Pending.Count == 0 || Id.Length == 0)
                    return;
                rows = new List<Dictionary<string, object>>(Pending);
                feedback = _feedback;
            }
            var body = new Dictionary<string, object>
            {
                ["installId"] = Id,
                ["appVersion"] = AppVersion(),
                ["source"] = "setup",
                ["events"] = rows,
            };
            if (feedback != null)
                body["feedback"] = feedback;
            if (!Post(new JavaScriptSerializer().Serialize(body)))
                return;
            lock (Lock)
            {
                Pending.RemoveRange(0, Math.Min(rows.Count, Pending.Count));
                if (ReferenceEquals(_feedback, feedback))
                    _feedback = null;
            }
        }

        // True when the Store took the batch (a refusal answers 200 with an "error").
        static bool Post(string json)
        {
            try
            {
                var baseUrl = WebRelease.BaseUrl(Environment.GetEnvironmentVariable(WebRelease.BaseUrlEnv));
                var req = (HttpWebRequest)WebRequest.Create(baseUrl + CollectPath);
                req.Method = "POST";
                req.Accept = "application/json";
                req.ContentType = "application/json";
                req.UserAgent = Web.UserAgent();
                // Collect routes want Origin to match the site, like the app's own calls.
                req.Headers["Origin"] = baseUrl;
                req.Timeout = 10000;
                req.ReadWriteTimeout = 10000;
                var data = Encoding.UTF8.GetBytes(json);
                req.ContentLength = data.Length;
                using (var s = req.GetRequestStream())
                    s.Write(data, 0, data.Length);
                using var resp = (HttpWebResponse)req.GetResponse();
                using var reader = new StreamReader(resp.GetResponseStream()!, Encoding.UTF8);
                var answer = reader.ReadToEnd();
                return answer.IndexOf("\"error\"", StringComparison.Ordinal) < 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        static string AppVersion()
        {
            var v = typeof(Usage).Assembly.GetName().Version;
            return v == null ? "0.0.0" : v.ToString(3);
        }
    }
}
