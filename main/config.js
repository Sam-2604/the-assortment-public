/* ============================================================
   THE ASSORTMENT — Supabase config
   ------------------------------------------------------------
   Paste your two values from the Supabase dashboard:
     Project Settings  →  API
       • Project URL  (a.k.a. "API URL")  → SUPABASE_URL
       • anon public key                  → SUPABASE_ANON_KEY

   Both are SAFE to commit publicly. The anon key is designed
   to be exposed in the browser — it's your Row Level Security
   policies that keep takes private, not the secrecy of this key.

   NEVER paste the `service_role` key here. Only the anon key.
   ============================================================ */

const SUPABASE_URL      = "https://jihlrxrdwxnwuledtnix.supabase.co";
const SUPABASE_ANON_KEY = "sb_publishable_0L2UKy74UBszKTxb1vW15A_TNPPy53i";