#define PROBE_SELF_TEST
#include "../../../scripts/broker/native/simnow_query_control.cpp"
#include <cassert>
#include <iostream>
int main() {
    { Probe p; p.phase=110; p.query_response(110,110,nullptr,true,false,true);
      assert(p.wait(0)); assert(p.terminal && p.callbacks==1 && p.rows==0); }
    { Probe p; p.phase=110; assert(!p.wait(0)); assert(p.status=="ZERO_CALLBACK_TIMEOUT");
      p.query_response(110,110,nullptr,true,false,true); assert(p.failed && !p.terminal && p.callbacks==0); }
    { Probe p; p.phase=110; p.query_response(110,110,nullptr,false,true,true);
      assert(!p.wait(0)); assert(p.status=="TERMINATOR_TIMEOUT" && p.rows==1); }
    { Probe p; p.phase=110; p.query_response(110,111,nullptr,true,false,true);
      assert(p.failed && p.status=="RESPONSE_ID_MISMATCH"); }
    { Probe p; p.phase=110; p.query_response(110,110,nullptr,true,true,false);
      assert(p.failed && p.rows==0 && p.status=="QUERY_IDENTITY_INVALID"); }
    { Probe p; p.phase=110; CThostFtdcRspInfoField info{}; info.ErrorID=3;
      p.query_response(110,110,&info,true,false,true); assert(p.failed && p.error==3); }
    { Probe p; p.phase=110; std::thread callback([&]{
          std::lock_guard<std::mutex> lock(p.mu); p.query_response(110,110,nullptr,true,true,true);
      }); assert(p.wait(1)); callback.join(); assert(p.rows==1); }
    { Probe p; p.phase=111; strcpy(p.user,"123"); strcpy(p.day,"20261026");
      CThostFtdcTradingAccountField row{}; strcpy(row.BrokerID,"9999"); strcpy(row.AccountID,"123");
      strcpy(row.TradingDay,"20261026"); strcpy(row.CurrencyID,"CNY");
      p.OnRspQryTradingAccount(&row,nullptr,111,true); assert(p.wait(0) && p.rows==1); }
    { Probe p; p.phase=110; p.query_response(110,110,nullptr,true,false,true);
      p.query_response(110,110,nullptr,true,false,true); assert(p.failed); }
    { char unterminated[4]={'9','9','9','9'}; assert(!equals(unterminated,"9999")); }
    std::cout << "10 native callback cases passed (offline; no Broker calls)\n";
}
