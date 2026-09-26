using System.Net.Http;
using System.Windows;
using System.Windows.Media;

namespace PlayZoneManager.Desktop;

public partial class MainWindow : Window
{
    private static readonly Uri LocalUi = new("http://127.0.0.1:8000/");
    private static readonly Uri HealthUrl = new("http://127.0.0.1:8000/api/health");
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(1.5) };
    private readonly CancellationTokenSource _closing = new();

    public MainWindow()
    {
        InitializeComponent();
        Loaded += async (_, _) => await ConnectAsync();
        Closed += (_, _) =>
        {
            _closing.Cancel();
            _http.Dispose();
            _closing.Dispose();
        };
    }

    private async Task ConnectAsync()
    {
        SetStatus(false, "Connecting to Local Edge...");
        ErrorText.Text = "";

        for (var attempt = 1; attempt <= 20 && !_closing.IsCancellationRequested; attempt++)
        {
            try
            {
                using var response = await _http.GetAsync(HealthUrl, _closing.Token);
                if (response.IsSuccessStatusCode)
                {
                    await OpenLocalUiAsync();
                    return;
                }
                ErrorText.Text = $"Local Edge returned HTTP {(int)response.StatusCode}.";
            }
            catch (OperationCanceledException) when (_closing.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex)
            {
                ErrorText.Text = "خدمة PlayZone المحلية غير متاحة بعد.\n" + ex.Message;
            }

            try
            {
                await Task.Delay(500, _closing.Token);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }

        SetStatus(false, "Local Edge Offline");
        OfflinePanel.Visibility = Visibility.Visible;
        Browser.Visibility = Visibility.Collapsed;
    }

    private async Task OpenLocalUiAsync()
    {
        await Browser.EnsureCoreWebView2Async();
        Browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
        Browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
        Browser.Source = LocalUi;
        Browser.Visibility = Visibility.Visible;
        OfflinePanel.Visibility = Visibility.Collapsed;
        SetStatus(true, "Local Edge Online");
    }

    private void SetStatus(bool online, string text)
    {
        StatusText.Text = text;
        StatusDot.Fill = new SolidColorBrush(
            online ? Color.FromRgb(99, 230, 166) : Color.FromRgb(255, 140, 140)
        );
    }

    private async void Retry_Click(object sender, RoutedEventArgs e)
    {
        await ConnectAsync();
    }
}
