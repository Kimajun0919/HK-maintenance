using System;
using System.Windows;

namespace HKMaintenanceWindowsApp;

public partial class MainWindow : Window
{
    private const string DefaultUrl = "http://127.0.0.1:7860";

    public MainWindow()
    {
        InitializeComponent();
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        await WebView.EnsureCoreWebView2Async();
        WebView.Source = new Uri(DefaultUrl);
    }
}
