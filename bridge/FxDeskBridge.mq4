//+------------------------------------------------------------------+
//|                                                FxDeskBridge.mq4  |
//|  File-based bridge between MetaTrader 4 and the fxdesk Python     |
//|  client. Copy to MQL4/Experts, compile, and attach to one chart.  |
//+------------------------------------------------------------------+
#property strict
#property description "fxdesk MT4 file bridge"
#property version   "1.00"

input string BridgeFolder   = "fxdesk"; // folder under MQL4/Files
input int    TimerMs        = 200;      // command poll interval
input int    SlippagePoints = 3;        // OrderSend/OrderClose slippage

string g_folder;

int OnInit()
{
   g_folder = BridgeFolder;
   FolderCreate(g_folder);
   EventSetMillisecondTimer(TimerMs);
   Print("fxdesk bridge listening in MQL4/Files/", g_folder);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   ProcessCommands();
}

void ProcessCommands()
{
   string fileName;
   int handle = FileFindFirst(g_folder + "\\cmd_*.txt", fileName);
   if(handle == INVALID_HANDLE)
      return;

   do
   {
      string base = BaseName(fileName);
      if(StringFind(base, "cmd_") == 0 && StringLen(base) > 8)
      {
         string id = StringSubstr(base, 4, StringLen(base) - 8);
         ProcessCommand(id);
      }
   }
   while(FileFindNext(handle, fileName));

   FileFindClose(handle);
}

string BaseName(string path)
{
   string result = path;
   int pos = StringFind(result, "\\");
   while(pos >= 0)
   {
      result = StringSubstr(result, pos + 1);
      pos = StringFind(result, "\\");
   }
   return result;
}

void ProcessCommand(string id)
{
   string cmdPath = g_folder + "\\cmd_" + id + ".txt";
   int handle = FileOpen(cmdPath, FILE_READ | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return;

   string lines[];
   int count = 0;
   while(!FileIsEnding(handle))
   {
      string line = FileReadString(handle);
      if(StringLen(line) > 0)
      {
         ArrayResize(lines, count + 1);
         lines[count] = line;
         count++;
      }
   }
   FileClose(handle);

   string action = "";
   string symbol = "";
   string side = "";
   string comment = "";
   double volume = 0.0;
   double sl = 0.0;
   double tp = 0.0;
   long ticket = 0;

   for(int i = 0; i < count; i++)
   {
      string line = lines[i];
      int eq = StringFind(line, "=");
      if(eq <= 0)
         continue;

      string key = ToUpper(StringSubstr(line, 0, eq));
      string value = StringSubstr(line, eq + 1);

      if(key == "ACTION")
         action = ToLower(value);
      else if(key == "SYMBOL")
         symbol = value;
      else if(key == "SIDE")
         side = ToLower(value);
      else if(key == "VOLUME")
         volume = StringToDouble(value);
      else if(key == "SL")
         sl = StringToDouble(value);
      else if(key == "TP")
         tp = StringToDouble(value);
      else if(key == "TICKET")
         ticket = StringToInteger(value);
      else if(key == "COMMENT")
         comment = value;
   }

   string response = HandleCommand(action, symbol, side, volume, sl, tp, ticket, comment);
   WriteResponse(id, response);
   FileDelete(cmdPath);
}

string HandleCommand(string action, string symbol, string side, double volume,
                     double sl, double tp, long ticket, string comment)
{
   if(action == "ping")
      return "OK=1\nMESSAGE=pong\n";

   if(action == "account")
   {
      string r = "OK=1\n";
      r += "BALANCE=" + DoubleToString(AccountBalance(), 2) + "\n";
      r += "EQUITY=" + DoubleToString(AccountEquity(), 2) + "\n";
      r += "CURRENCY=" + AccountCurrency() + "\n";
      r += "LEVERAGE=" + IntegerToString(AccountLeverage()) + "\n";
      r += "MARGINFREE=" + DoubleToString(AccountFreeMargin(), 2) + "\n";
      r += "BROKER=" + AccountCompany() + "\n";
      return r;
   }

   if(action == "symbol")
      return SymbolResponse(symbol);

   if(action == "quote")
      return QuoteResponse(symbol);

   if(action == "order")
      return OrderResponse(symbol, side, volume, sl, tp, comment);

   if(action == "positions")
      return PositionsResponse(symbol);

   if(action == "close")
      return CloseResponse(ticket);

   return "OK=0\nMESSAGE=unknown action\n";
}

string SymbolResponse(string symbol)
{
   if(symbol == "")
      return "OK=0\nMESSAGE=symbol required\n";

   double point = MarketInfo(symbol, MODE_POINT);
   if(point <= 0)
      return "OK=0\nMESSAGE=unknown symbol\n";

   int digits = (int)MarketInfo(symbol, MODE_DIGITS);
   double pip = point;
   if(digits == 3 || digits == 5)
      pip = point * 10.0;

   string r = "OK=1\n";
   r += "DIGITS=" + IntegerToString(digits) + "\n";
   r += "POINT=" + DoubleToString(point, 10) + "\n";
   r += "PIP=" + DoubleToString(pip, 10) + "\n";
   r += "CONTRACT=" + DoubleToString(MarketInfo(symbol, MODE_LOTSIZE), 2) + "\n";
   r += "MINLOT=" + DoubleToString(MarketInfo(symbol, MODE_MINLOT), 2) + "\n";
   r += "LOTSTEP=" + DoubleToString(MarketInfo(symbol, MODE_LOTSTEP), 2) + "\n";
   r += "MAXLOT=" + DoubleToString(MarketInfo(symbol, MODE_MAXLOT), 2) + "\n";
   r += "SPREAD=" + DoubleToString(MarketInfo(symbol, MODE_SPREAD) * point, 10) + "\n";
   return r;
}

string QuoteResponse(string symbol)
{
   if(symbol == "")
      return "OK=0\nMESSAGE=symbol required\n";

   RefreshRates();
   double bid = MarketInfo(symbol, MODE_BID);
   double ask = MarketInfo(symbol, MODE_ASK);
   if(bid <= 0 || ask <= 0)
      return "OK=0\nMESSAGE=no quote\n";

   int digits = (int)MarketInfo(symbol, MODE_DIGITS);
   string r = "OK=1\n";
   r += "BID=" + DoubleToString(bid, digits) + "\n";
   r += "ASK=" + DoubleToString(ask, digits) + "\n";
   r += "TIME=" + TimeToStr(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\n";
   return r;
}

string OrderResponse(string symbol, string side, double volume, double sl,
                     double tp, string comment)
{
   if(symbol == "")
      return "OK=0\nMESSAGE=symbol required\n";
   if(volume <= 0)
      return "OK=0\nMESSAGE=volume must be positive\n";
   if(side != "buy" && side != "sell")
      return "OK=0\nMESSAGE=side must be buy or sell\n";

   RefreshRates();
   int digits = (int)MarketInfo(symbol, MODE_DIGITS);
   double price = (side == "buy") ? MarketInfo(symbol, MODE_ASK)
                                  : MarketInfo(symbol, MODE_BID);
   if(price <= 0)
      return "OK=0\nMESSAGE=no quote\n";

   if(sl > 0)
      sl = NormalizeDouble(sl, digits);
   else
      sl = 0;
   if(tp > 0)
      tp = NormalizeDouble(tp, digits);
   else
      tp = 0;

   int cmd = (side == "buy") ? OP_BUY : OP_SELL;
   int ticket = OrderSend(symbol, cmd, volume, NormalizeDouble(price, digits),
                          SlippagePoints, sl, tp, comment, 0, 0, 0);
   if(ticket < 0)
      return "OK=0\nMESSAGE=" + IntegerToString(GetLastError()) + "\n";

   string r = "OK=1\n";
   r += "TICKET=" + IntegerToString(ticket) + "\n";
   r += "PRICE=" + DoubleToString(price, digits) + "\n";
   r += "RETCODE=0\n";
   return r;
}

string PositionsResponse(string symbol)
{
   string r = "OK=1\n";
   int total = OrdersTotal();

   for(int i = 0; i < total; i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;
      if(OrderType() != OP_BUY && OrderType() != OP_SELL)
         continue;
      if(symbol != "" && OrderSymbol() != symbol)
         continue;

      int digits = (int)MarketInfo(OrderSymbol(), MODE_DIGITS);
      string side = (OrderType() == OP_BUY) ? "buy" : "sell";
      r += "POSITION=" + IntegerToString(OrderTicket()) + "|" +
           OrderSymbol() + "|" + side + "|" +
           DoubleToString(OrderLots(), 2) + "|" +
           DoubleToString(OrderOpenPrice(), digits) + "|" +
           DoubleToString(OrderStopLoss(), digits) + "|" +
           DoubleToString(OrderTakeProfit(), digits) + "|" +
           DoubleToString(OrderProfit(), 2) + "|" +
           OrderComment() + "|" +
           TimeToStr(OrderOpenTime(), TIME_DATE | TIME_SECONDS) + "\n";
   }
   return r;
}

string CloseResponse(long ticket)
{
   if(!OrderSelect((int)ticket, SELECT_BY_TICKET))
      return "OK=0\nMESSAGE=position not found\n";
   if(OrderType() != OP_BUY && OrderType() != OP_SELL)
      return "OK=0\nMESSAGE=not a market position\n";

   RefreshRates();
   int digits = (int)MarketInfo(OrderSymbol(), MODE_DIGITS);
   double price = (OrderType() == OP_BUY) ? MarketInfo(OrderSymbol(), MODE_BID)
                                          : MarketInfo(OrderSymbol(), MODE_ASK);
   if(price <= 0)
      return "OK=0\nMESSAGE=no quote\n";

   double profit = OrderProfit() + OrderSwap() + OrderCommission();
   bool ok = OrderClose((int)ticket, OrderLots(), NormalizeDouble(price, digits),
                        SlippagePoints, 0);
   if(!ok)
      return "OK=0\nMESSAGE=" + IntegerToString(GetLastError()) + "\n";

   string r = "OK=1\n";
   r += "PRICE=" + DoubleToString(price, digits) + "\n";
   r += "PROFIT=" + DoubleToString(profit, 2) + "\n";
   return r;
}

void WriteResponse(string id, string response)
{
   string resPath = g_folder + "\\res_" + id + ".txt";
   int handle = FileOpen(resPath, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
      return;
   FileWriteString(handle, response);
   FileClose(handle);
}

string ToUpper(string text)
{
   for(int i = 0; i < StringLen(text); i++)
   {
      int c = StringGetCharacter(text, i);
      if(c >= 97 && c <= 122)
         StringSetCharacter(text, i, c - 32);
   }
   return text;
}

string ToLower(string text)
{
   for(int i = 0; i < StringLen(text); i++)
   {
      int c = StringGetCharacter(text, i);
      if(c >= 65 && c <= 90)
         StringSetCharacter(text, i, c + 32);
   }
   return text;
}
//+------------------------------------------------------------------+
