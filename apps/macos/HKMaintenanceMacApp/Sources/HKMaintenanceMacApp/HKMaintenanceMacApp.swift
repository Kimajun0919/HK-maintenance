import SwiftUI
import WebKit

@main
struct HKMaintenanceMacApp: App {
    var body: some Scene {
        WindowGroup {
            WebAppView(url: URL(string: "http://127.0.0.1:7860")!)
                .frame(minWidth: 1180, minHeight: 760)
        }
    }
}

struct WebAppView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}
}
