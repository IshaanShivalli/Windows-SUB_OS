#include <Windows.h>
#include <winhttp.h>

#include <algorithm>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#pragma comment(lib, "winhttp.lib")

namespace {

volatile std::sig_atomic_t stop_requested = 0;

void handle_interrupt(int) {
    stop_requested = 1;
}

std::string format_mbps(double value) {
    std::ostringstream out;
    out << std::fixed << std::setprecision(2) << value << " Mbps";
    return out.str();
}

std::string graph(const std::vector<double>& history) {
    static constexpr char levels[] = " .:-=+*#%@";
    std::string result;
    for (double value : history) {
        const double scaled = std::clamp(value / 1000.0, 0.0, 1.0);
        const size_t index = static_cast<size_t>(scaled * (sizeof(levels) - 2));
        result += levels[index];
    }
    return result;
}

size_t progress_width(double value) {
    return static_cast<size_t>(std::clamp(value / 1000.0, 0.0, 1.0) * 24.0);
}

struct Sample {
    double download_mbps = 0.0;
    double upload_mbps = 0.0;
    double avg_download_mbps = 0.0;
    double avg_upload_mbps = 0.0;
    size_t samples = 0;
};

bool enable_virtual_terminal() {
    HANDLE output = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD mode = 0;
    if (output == INVALID_HANDLE_VALUE || !GetConsoleMode(output, &mode)) {
        return false;
    }
    return SetConsoleMode(output, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING) != 0;
}

void render_dashboard(const Sample& latest, const Sample& totals,
                      const std::vector<double>& download_history,
                      const std::vector<double>& upload_history,
                      size_t samples, double elapsed_seconds, bool ansi) {
    const char* cyan = ansi ? "\x1b[1;36m" : "";
    const char* green = ansi ? "\x1b[1;32m" : "";
    const char* yellow = ansi ? "\x1b[1;33m" : "";
    const char* dim = ansi ? "\x1b[2m" : "";
    const char* reset = ansi ? "\x1b[0m" : "";
    if (ansi) {
        std::cout << "\x1b[2J\x1b[H";
    }

    const size_t download_bar = progress_width(latest.download_mbps);
    const size_t upload_bar = progress_width(latest.upload_mbps);
    std::cout << cyan << "+------------------------------------------------------------------+" << reset << "\n"
              << cyan << "|                 OPERATOR NETWORK SPEED TEST                      |" << reset << "\n"
              << cyan << "+------------------------------------------------------------------+" << reset << "\n"
              << " Status: " << green << "RUNNING" << reset << "    Samples: " << samples
              << "    Duration: " << std::fixed << std::setprecision(1)
              << elapsed_seconds << " s\n\n"
              << " Download  " << std::setw(10) << format_mbps(latest.download_mbps)
              << "   Avg " << std::setw(10) << format_mbps(totals.avg_download_mbps)
              << "   [" << std::string(download_bar, '#')
              << std::string(24 - download_bar, ' ') << "]\n"
              << " Upload    " << std::setw(10) << format_mbps(latest.upload_mbps)
              << "   Avg " << std::setw(10) << format_mbps(totals.avg_upload_mbps)
              << "   [" << std::string(upload_bar, '#')
              << std::string(24 - upload_bar, ' ') << "]\n\n"
              << " Download history  " << graph(download_history) << "\n"
              << " Upload history    " << graph(upload_history) << "\n\n"
              << dim << "Bars scale to 1000 Mbps. Each sample transfers about 1 MB "
                    "in each direction." << reset << "\n"
              << cyan << "--------------------------------------------------------------------" << reset << "\n"
              << " Press " << yellow << "Ctrl+C" << reset << " to stop.\n"
              << std::flush;
}

std::string download_url(const std::string& base, size_t bytes) {
    std::ostringstream url;
    url << base << "?bytes=" << bytes << "&operator_sample=" << std::hex << std::this_thread::get_id();
    return url.str();
}

bool request_bytes(const std::string& url, std::vector<char>& buffer, size_t limit_bytes) {
    HINTERNET session = WinHttpOpen(L"AtlasNetSpeed/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                   WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) {
        return false;
    }

    std::wstring wurl(url.begin(), url.end());
    HINTERNET connection = WinHttpConnect(session, L"speed.cloudflare.com", INTERNET_DEFAULT_HTTPS_PORT, 0);
    HINTERNET request = nullptr;
    if (connection) {
        request = WinHttpOpenRequest(connection, L"GET", L"__down", nullptr, WINHTTP_NO_REFERER,
                                    WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE);
    }
    if (!request) {
        WinHttpCloseHandle(session);
        return false;
    }

    BOOL ok = WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS, 0, WINHTTP_NO_REQUEST_DATA, 0,
                                 0, 0);
    if (ok) {
        ok = WinHttpReceiveResponse(request, nullptr);
    }

    DWORD status_code = 0;
    DWORD status_size = sizeof(status_code);
    if (ok && WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                                  WINHTTP_HEADER_NAME_BY_INDEX, &status_code, &status_size, WINHTTP_NO_HEADER_INDEX)) {
        if (status_code != 200) {
            WinHttpCloseHandle(request);
            WinHttpCloseHandle(connection);
            WinHttpCloseHandle(session);
            return false;
        }
    }

    buffer.clear();
    DWORD bytes_read = 0;
    do {
        char chunk[65536];
        DWORD read_now = 0;
        ok = WinHttpReadData(request, chunk, sizeof(chunk), &read_now);
        if (!ok || read_now == 0) break;
        size_t remaining = limit_bytes - buffer.size();
        if (remaining > 0) {
            size_t copy_len = std::min<size_t>(remaining, read_now);
            buffer.insert(buffer.end(), chunk, chunk + copy_len);
        }
        bytes_read += read_now;
    } while (bytes_read < limit_bytes);

    WinHttpCloseHandle(request);
    WinHttpCloseHandle(connection);
    WinHttpCloseHandle(session);
    return true;
}

Sample sample_once() {
    const size_t payload_size = 1'000'000;
    Sample out;
    auto t0 = std::chrono::steady_clock::now();
    std::vector<char> download_buffer;
    const bool ok = request_bytes(download_url("https://speed.cloudflare.com/__down", payload_size), download_buffer, payload_size);
    auto t1 = std::chrono::steady_clock::now();
    double elapsed = std::max(0.001, std::chrono::duration<double>(t1 - t0).count());
    out.download_mbps = (download_buffer.size() * 8.0) / elapsed / 1'000'000.0;

    auto upload_start = std::chrono::steady_clock::now();
    std::string upload_data(payload_size, 'A');
    std::wstring upload_url = L"https://speed.cloudflare.com/__up";
    HINTERNET session = WinHttpOpen(L"AtlasNetSpeed/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                   WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    HINTERNET connection = WinHttpConnect(session, L"speed.cloudflare.com", INTERNET_DEFAULT_HTTPS_PORT, 0);
    HINTERNET request = WinHttpOpenRequest(connection, L"POST", L"__up", nullptr, WINHTTP_NO_REFERER,
                                          WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE);
    if (request) {
        std::wstring headers = L"Content-Type: application/octet-stream\r\n";
        BOOL sent = WinHttpSendRequest(request, headers.c_str(), -1L, const_cast<void*>(reinterpret_cast<const void*>(upload_data.data())),
                                      static_cast<DWORD>(upload_data.size()), static_cast<DWORD>(upload_data.size()), 0);
        if (sent) {
            WinHttpReceiveResponse(request, nullptr);
        }
    }
    auto upload_end = std::chrono::steady_clock::now();
    double upload_elapsed = std::max(0.001, std::chrono::duration<double>(upload_end - upload_start).count());
    out.upload_mbps = (upload_data.size() * 8.0) / upload_elapsed / 1'000'000.0;

    if (session) WinHttpCloseHandle(session);
    if (connection) WinHttpCloseHandle(connection);
    if (request) WinHttpCloseHandle(request);
    return out;
}

}  // namespace

int main() {
    std::signal(SIGINT, handle_interrupt);
    const bool ansi = enable_virtual_terminal();
    Sample total;
    Sample latest;
    size_t sample_count = 0;
    std::vector<double> download_history;
    std::vector<double> upload_history;
    const auto started = std::chrono::steady_clock::now();
    if (ansi) {
        std::cout << "\x1b[?25l";
    }
    try {
        while (!stop_requested) {
            latest = sample_once();
            if (stop_requested) {
                break;
            }
            Sample sample = latest;
            total.download_mbps += sample.download_mbps;
            total.upload_mbps += sample.upload_mbps;
            sample_count += 1;
            total.avg_download_mbps = total.download_mbps / sample_count;
            total.avg_upload_mbps = total.upload_mbps / sample_count;

            download_history.push_back(sample.download_mbps);
            upload_history.push_back(sample.upload_mbps);
            if (download_history.size() > 64) {
                download_history.erase(download_history.begin());
                upload_history.erase(upload_history.begin());
            }
            const double elapsed = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - started).count();
            render_dashboard(latest, total, download_history, upload_history,
                             sample_count, elapsed, ansi);

            std::this_thread::sleep_for(std::chrono::seconds(1));
        }
    } catch (const std::exception& error) {
        if (ansi) {
            std::cout << "\x1b[?25h";
        }
        std::cerr << "\n[SPEED TEST ERROR] " << error.what() << std::endl;
        return 1;
    }
    if (ansi) {
        std::cout << "\x1b[?25h";
    }
    std::cout << "\n[SPEED TEST STOPPED] " << sample_count
              << " sample(s) completed." << std::endl;
    return 0;
}
