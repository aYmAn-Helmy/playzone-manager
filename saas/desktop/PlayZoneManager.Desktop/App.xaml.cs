using System.IO;
using System.Windows;
using System.Windows.Threading;

namespace PlayZoneManager.Desktop;

public partial class App : Application
{
    public App()
    {
        DispatcherUnhandledException += OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;
    }

    private static string LogPath
    {
        get
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "PlayZone Manager",
                "logs"
            );
            Directory.CreateDirectory(dir);
            return Path.Combine(dir, "desktop-crash.log");
        }
    }

    private static void WriteCrash(Exception ex)
    {
        try
        {
            File.AppendAllText(
                LogPath,
                $"[{DateTimeOffset.Now:O}] {ex}\r\n\r\n"
            );
        }
        catch
        {
            // Never allow logging failure to hide the original error.
        }
    }

    private void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        WriteCrash(e.Exception);
        MessageBox.Show(
            "PlayZone Manager could not start correctly.\n\n" +
            e.Exception.Message +
            "\n\nCrash log:\n" + LogPath,
            "PlayZone Manager",
            MessageBoxButton.OK,
            MessageBoxImage.Error
        );
        e.Handled = true;
        Shutdown(-1);
    }

    private static void OnUnhandledException(object? sender, UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
            WriteCrash(ex);
    }
}
