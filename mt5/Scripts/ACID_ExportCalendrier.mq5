//+------------------------------------------------------------------+
//|  ACID_ExportCalendrier.mq5                                       |
//|  16/09/2026 — L'HISTORIQUE DU CALENDRIER, UNE BONNE FOIS          |
//+------------------------------------------------------------------+
//
//  POURQUOI CE SCRIPT EXISTE
//
//  Le patron : «…
//  …» — puis, sur la question de savoir si
//  ça rapporte vraiment : on mesure avant de croire.
//
//  Or on ne peut PAS mesurer sans l'historique des événements, et il n'existe
//  nulle part d'accessible :
//    · le paquet Python de MT5 a 46 fonctions, AUCUNE pour le calendrier
//      (vérifié le 16/09 : copy_rates, positions_get, order_send… et rien d'autre)
//    · bases/<serveur>/news/news.dat est la tab «…» — des articles
//      FXStreet. Zéro «…», zéro événement daté. Inutilisable.
//    · acid_calendrier.txt que l'EA écrit ne contient que le jour même.
//
//  Seul MQL5 sait lire l'historique : CalendarValueHistory(). D'où ce script.
//  Il tourne UNE fois, écrit un CSV, et s'arrête. Il ne trade pas, ne touche
//  à aucune position, ne modifie aucun réglage. On peut le lancer pendant que
//  l'EA travaille : il ne fait que lire et écrire un fichier.
//
//  COMMENT S'EN SERVIR
//    Navigateur (Ctrl+N) -> Scripts -> ACID_ExportCalendrier
//    double-clic, ou glisser sur n'importe quel graphique.
//    Le résultat arrive dans MQL5/Files/acid_calendrier_histo.csv
//
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input int  AnneesEnArriere = 3;      // profondeur d'historique à exporter
input bool SeulementHaute  = false;  // false = tout, pour pouvoir comparer les niveaux

//+------------------------------------------------------------------+
void OnStart()
{
   datetime fin   = TimeTradeServer() + 30*86400;          // +30 j : les à-venir aussi
   datetime debut = fin - (datetime)AnneesEnArriere*365*86400;

   MqlCalendarValue vals[];
   int n = CalendarValueHistory(vals, debut, fin);
   if(n <= 0)
   {
      Print("❌ calendrier vide ou indisponible (", GetLastError(), "). ",
            "Vérifie que l'onglet Calendrier est activé dans MT5 ",
            "(Outils > Options > Communauté / Calendrier) et réessaie.");
      return;
   }

   int h = FileOpen("acid_calendrier_histo.csv", FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE)
   {
      Print("❌ impossible d'écrire le fichier (", GetLastError(), ")");
      return;
   }

   FileWriteString(h, "# genere par ACID_ExportCalendrier le " +
                      TimeToString(TimeTradeServer(), TIME_DATE|TIME_MINUTES) + "\n");
   FileWriteString(h, "# horodatage_serveur|devise|importance|nom\n");

   // Les libellés d'événement et la devise ne sont PAS dans MqlCalendarValue :
   // il faut remonter à l'événement, puis au pays. On met les deux en cache,
   // sinon on refait des milliers d'allers-retours pour les mêmes identifiants.
   ulong  ev_vus[];   string ev_nom[];  string ev_dev[];  int ev_imp[];
   int    cache = 0;
   int    ecrits = 0, hautes = 0, moyennes = 0;

   for(int i = 0; i < n; i++)
   {
      ulong  id = vals[i].event_id;
      int    k  = -1;
      for(int j = 0; j < cache; j++) if(ev_vus[j] == id) { k = j; break; }

      if(k < 0)
      {
         MqlCalendarEvent ev;
         if(!CalendarEventById(id, ev)) continue;
         MqlCalendarCountry pays;
         string devise = "";
         if(CalendarCountryById(ev.country_id, pays)) devise = pays.currency;

         k = cache;
         ArrayResize(ev_vus, cache+1); ArrayResize(ev_nom, cache+1);
         ArrayResize(ev_dev, cache+1); ArrayResize(ev_imp, cache+1);
         ev_vus[k] = id;
         ev_nom[k] = ev.name;
         ev_dev[k] = devise;
         ev_imp[k] = (int)ev.importance;
         cache++;
      }

      string imp = "LOW";
      if(ev_imp[k] == CALENDAR_IMPORTANCE_HIGH)        { imp = "HIGH";   hautes++;   }
      else if(ev_imp[k] == CALENDAR_IMPORTANCE_MODERATE){ imp = "MEDIUM"; moyennes++; }
      else if(SeulementHaute) continue;

      if(ev_dev[k] == "") continue;      // sans devise, on ne peut rien rattacher

      FileWriteString(h, StringFormat("%d|%s|%s|%s\n",
                        (int)vals[i].time, ev_dev[k], imp, ev_nom[k]));
      ecrits++;
   }
   FileClose(h);

   PrintFormat("✅ %d evenements ecrits (%d HIGH, %d MEDIUM) sur %d lus, %d libelles distincts",
               ecrits, hautes, moyennes, n, cache);
   PrintFormat("   du %s au %s",
               TimeToString(debut, TIME_DATE), TimeToString(fin, TIME_DATE));
   Print("   fichier : MQL5/Files/acid_calendrier_histo.csv");
}
//+------------------------------------------------------------------+
