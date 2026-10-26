// Diagnostic only. Same Mac SDK, endpoint and initialization as Python probe.
#include "ThostFtdcTraderApi.h"
#include <CommonCrypto/CommonDigest.h>
#include <readpassphrase.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <cstdio>
#include <mutex>
#include <string>
#include <thread>
#include <filesystem>
#include <cerrno>

static void wipe(void* ptr, size_t size) { volatile unsigned char* p = static_cast<volatile unsigned char*>(ptr); while (size--) *p++ = 0; }
template<size_t N> static bool equals(const char (&value)[N], const char* expected) {
    return strnlen(value,N) < N && strcmp(value,expected)==0;
}
struct Probe final : CThostFtdcTraderSpi {
    CThostFtdcTraderApi* api = nullptr;
    std::mutex mu;
    std::condition_variable cv;
    char user[sizeof(TThostFtdcInvestorIDType)]{};
    char password[41]{};
    static_assert(sizeof(TThostFtdcUserIDType)>=sizeof(TThostFtdcInvestorIDType));
    static_assert(sizeof(TThostFtdcPasswordType)>=41);
    char day[9]{};
    std::string status = "CONNECTING";
    int phase = 0, rows = 0, callbacks = 0, rc = -999, error = 0;
    bool done = false, terminal = false, failed = false;
    int auth_attempts = 0, login_attempts = 0, query_attempts = 0;
    void fail(const char* reason, int code = 0) {
        if (!failed) { status = reason; error = code; failed = true; }
        cv.notify_all();
    }
    bool response(int id, int expected, CThostFtdcRspInfoField* info) {
        if (failed) return false;
        if (id != expected) { fail("RESPONSE_ID_MISMATCH"); return false; }
        if (info && info->ErrorID) { fail("SERVER_REJECTED", info->ErrorID); return false; }
        return true;
    }
    void OnFrontConnected() override {
        std::lock_guard<std::mutex> lock(mu);
        if (phase || failed) { fail("UNEXPECTED_RECONNECT"); return; }
        phase = 1;
        CThostFtdcReqAuthenticateField req{};
        strcpy(req.BrokerID, "9999"); strcpy(req.UserID, user);
        strcpy(req.AppID, "simnow_client_test"); strcpy(req.AuthCode, "0000000000000000");
        ++auth_attempts; rc = api->ReqAuthenticate(&req, 1);
        if (rc) fail("AUTH_NOT_ACCEPTED");
    }
    void OnFrontDisconnected(int) override {
        std::lock_guard<std::mutex> lock(mu); fail("DISCONNECTED");
    }
    void OnRspError(CThostFtdcRspInfoField* info, int, bool) override {
        std::lock_guard<std::mutex> lock(mu); fail("SERVER_ERROR", info ? info->ErrorID : -1);
    }
    void OnRspAuthenticate(CThostFtdcRspAuthenticateField* data, CThostFtdcRspInfoField* info, int id, bool last) override {
        std::lock_guard<std::mutex> lock(mu);
        if (!response(id, 1, info)) return;
        if (phase != 1 || !last || !data || !equals(data->BrokerID,"9999") || !equals(data->UserID,user)) {
            fail("AUTH_IDENTITY_INVALID"); return;
        }
        phase = 2;
        CThostFtdcReqUserLoginField req{};
        strcpy(req.BrokerID,"9999"); strcpy(req.UserID,user); strcpy(req.Password,password);
        ++login_attempts; rc = api->ReqUserLogin(&req, 2, 0, nullptr);
        wipe(req.Password, sizeof(req.Password)); wipe(password, sizeof(password));
        if (rc) fail("LOGIN_NOT_ACCEPTED");
    }
    void OnRspUserLogin(CThostFtdcRspUserLoginField* data, CThostFtdcRspInfoField* info, int id, bool last) override {
        std::lock_guard<std::mutex> lock(mu);
        if (!response(id, 2, info)) return;
        if (phase != 2 || !last || !data || !equals(data->BrokerID,"9999") || !equals(data->UserID,user)
            || strnlen(data->TradingDay, sizeof(data->TradingDay)) != 8
            || strspn(data->TradingDay,"0123456789") != 8) { fail("LOGIN_IDENTITY_INVALID"); return; }
        strcpy(day,data->TradingDay); phase = 3; done = true; status = "LOGIN_PASSED"; cv.notify_all();
    }
    void query_response(int expected, int id, CThostFtdcRspInfoField* info, bool last,
                        bool has_data, bool identity_ok) {
        if (!response(id, expected, info)) return;
        if (phase != expected || terminal || !identity_ok) { fail("QUERY_IDENTITY_INVALID"); return; }
        ++callbacks; if (has_data) ++rows;
        if (last) { terminal = true; done = true; cv.notify_all(); }
    }
    void OnRspQryInvestorPosition(CThostFtdcInvestorPositionField* data, CThostFtdcRspInfoField* info, int id, bool last) override {
        std::lock_guard<std::mutex> lock(mu);
        query_response(110,id,info,last,data, !data || (equals(data->BrokerID,"9999")
            && equals(data->InvestorID,user) && equals(data->TradingDay,day)));
    }
    void OnRspQryTradingAccount(CThostFtdcTradingAccountField* data, CThostFtdcRspInfoField* info, int id, bool last) override {
        std::lock_guard<std::mutex> lock(mu);
        query_response(111,id,info,last,data, !data || (equals(data->BrokerID,"9999")
            && equals(data->AccountID,user) && equals(data->CurrencyID,"CNY") && equals(data->TradingDay,day)));
    }
    bool wait(int seconds) {
        std::unique_lock<std::mutex> lock(mu);
        if (!cv.wait_for(lock,std::chrono::seconds(seconds),[&]{return done || failed;})) {
            fail(callbacks ? "TERMINATOR_TIMEOUT" : "ZERO_CALLBACK_TIMEOUT"); return false;
        }
        return !failed;
    }
    ~Probe() { wipe(user,sizeof(user)); wipe(password,sizeof(password)); }
};

#ifndef PROBE_SELF_TEST
int main(int argc, char** argv) {
    const char* version = CThostFtdcTraderApi::GetApiVersion();
    if (strcmp(version,"v6.7.7_MacOS_20240716 15:00:00")) return 2;
    if (argc == 2 && !strcmp(argv[1],"--version-check")) { puts("MAC_SDK_VERSION_MATCHED"); return 0; }
    if (argc != 2 || !isatty(STDIN_FILENO)) return 2;
    // Parent launcher supplies a new exclusive local output path, never credentials.
    int output = open(argv[1],O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
    if (output < 0) return 2;
    Probe probe;
    char input[1024]{};
    if (!readpassphrase("投资者代码：",input,sizeof(input),RPP_ECHO_ON|RPP_REQUIRE_TTY)
        || !strlen(input) || strlen(input)>=sizeof(TThostFtdcInvestorIDType) || strspn(input,"0123456789")!=strlen(input)) { close(output); return 2; }
    strcpy(probe.user,input); wipe(input,sizeof(input));
    if (!readpassphrase("交易密码（隐藏输入）：",input,sizeof(input),RPP_REQUIRE_TTY)
        || !strlen(input) || strlen(input)>40) { wipe(input,sizeof(input)); close(output); return 2; }
    strcpy(probe.password,input); wipe(input,sizeof(input));
    std::string identity = "[\"SIMNOW_FIRST\",\"9999\",\"" + std::string(probe.user) + "\"]";
    unsigned char hash[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(identity.data(),static_cast<CC_LONG>(identity.size()),hash);
    wipe(identity.data(),identity.size());
    char fingerprint[65]{}; for (int i=0;i<32;++i) snprintf(fingerprint+2*i,3,"%02x",hash[i]);
    char flow[] = "/private/tmp/guiyi-native-flow-XXXXXX";
    if (!mkdtemp(flow)) { close(output); return 2; }
    // No topic subscriptions: preserve original Python initialization for this control.
    int saved_out=dup(STDOUT_FILENO), saved_err=dup(STDERR_FILENO);
    int quiet=open("/dev/null",O_WRONLY);
    if(saved_out<0 || saved_err<0 || quiet<0 || dup2(quiet,STDOUT_FILENO)<0 || dup2(quiet,STDERR_FILENO)<0) {
        if(saved_out>=0) { dup2(saved_out,STDOUT_FILENO); close(saved_out); }
        if(saved_err>=0) { dup2(saved_err,STDERR_FILENO); close(saved_err); }
        if(quiet>=0) close(quiet);
        close(output); rmdir(flow); return 3;
    }
    close(quiet);
    std::string flow_path=std::string(flow)+"/";
    probe.api=CThostFtdcTraderApi::CreateFtdcTraderApi(flow_path.c_str());
    if (!probe.api) { dprintf(output,"{\"status\":\"API_CREATE_FAILED\",\"execution_eligible\":false}\n"); close(output); return 3; }
    probe.api->RegisterSpi(&probe);
    char front[]="tcp://182.254.243.31:30001";
    probe.api->RegisterFront(front); probe.api->Init();
    bool ok=probe.wait(25);
    int position_callbacks=0,position_rows=0,funds_callbacks=0,funds_rows=0;
    if(ok) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1100));
        { std::lock_guard<std::mutex> lock(probe.mu);
          if (!probe.failed) {
            probe.phase=110; probe.done=false; probe.callbacks=probe.rows=0;
            CThostFtdcQryInvestorPositionField req{}; strcpy(req.BrokerID,"9999"); strcpy(req.InvestorID,probe.user);
            ++probe.query_attempts; probe.rc=probe.api->ReqQryInvestorPosition(&req,110);
            if(probe.rc) probe.fail("QUERY_NOT_ACCEPTED");
          }
        }
        ok=probe.wait(45);
        { std::lock_guard<std::mutex> lock(probe.mu); position_callbacks=probe.callbacks; position_rows=probe.rows; }
    }
    if(ok) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1100));
        { std::lock_guard<std::mutex> lock(probe.mu);
          if (!probe.failed) {
            probe.phase=111; probe.done=false; probe.terminal=false; probe.callbacks=probe.rows=0;
            CThostFtdcQryTradingAccountField req{}; strcpy(req.BrokerID,"9999"); strcpy(req.InvestorID,probe.user); strcpy(req.CurrencyID,"CNY");
            ++probe.query_attempts; probe.rc=probe.api->ReqQryTradingAccount(&req,111);
            if(probe.rc) probe.fail("QUERY_NOT_ACCEPTED");
          }
        }
        ok=probe.wait(45);
        { std::lock_guard<std::mutex> lock(probe.mu); funds_callbacks=probe.callbacks; funds_rows=probe.rows;
          if (ok && probe.rows!=1) { probe.fail("FUNDS_ROW_COUNT_INVALID"); ok=false; }
        }
    }
    // Persist before Release, which may itself block. Terminal status is immutable.
    char report[2048]{}; int report_size=0;
    { std::lock_guard<std::mutex> lock(probe.mu);
      ok = ok && !probe.failed;
      if(ok) probe.status="DIAGNOSTIC_COMPLETE";
      report_size=snprintf(report,sizeof(report),"{\"client\":\"native_cpp_same_sdk\",\"environment_id\":\"SIMNOW_FIRST\",\"account_fingerprint\":\"%s\",\"status\":\"%s\",\"trading_day\":\"%s\",\"error_id\":%d,\"last_return_code\":%d,\"auth_attempts\":%d,\"login_attempts\":%d,\"query_attempts\":%d,\"position_callbacks\":%d,\"position_rows\":%d,\"funds_callbacks\":%d,\"funds_rows\":%d,\"order_requests\":0,\"execution_eligible\":false,\"account_acceptance\":false}\n",fingerprint,probe.status.c_str(),probe.day,probe.error,probe.rc,probe.auth_attempts,probe.login_attempts,probe.query_attempts,position_callbacks,position_rows,funds_callbacks,funds_rows);
    }
    bool persisted=report_size>0 && static_cast<size_t>(report_size)<sizeof(report);
    size_t written=0;
    while(persisted && written<static_cast<size_t>(report_size)) {
        ssize_t count=write(output,report+written,static_cast<size_t>(report_size)-written);
        if(count<0 && errno==EINTR) continue;
        if(count<=0) { persisted=false; break; }
        written+=static_cast<size_t>(count);
    }
    if(fsync(output)!=0) persisted=false;
    if(close(output)!=0) persisted=false;
    probe.api->RegisterSpi(nullptr); probe.api->Release();
    std::error_code cleanup_error; std::filesystem::remove_all(flow,cleanup_error);
    dup2(saved_out,STDOUT_FILENO); dup2(saved_err,STDERR_FILENO); close(saved_out); close(saved_err);
    puts("原生只读对照结束；结果不代表完整账户验收。");
    return persisted ? (ok?0:1) : 4;
}
#endif
