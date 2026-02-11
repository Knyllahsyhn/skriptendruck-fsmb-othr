"""
LDAP-Verbindungstest für HS Regensburg Active Directory.

Verwendung:
    python test_ldap.py <deine-rz-kennung> <dein-passwort> <zu-suchende-kennung>

Beispiel:
    python test_ldap.py mus43225 meinPasswort mus43225

Ohne Argumente wird interaktiv nach den Daten gefragt.
"""
import sys
import ssl
import traceback


def main() -> None:
    # === Eingabe ===
    if len(sys.argv) >= 4:
        bind_user = sys.argv[1]
        bind_pass = sys.argv[2]
        search_user = sys.argv[3]
    elif len(sys.argv) >= 3:
        bind_user = sys.argv[1]
        bind_pass = sys.argv[2]
        search_user = bind_user  # sich selbst suchen
    else:
        import getpass
        bind_user = input("Deine RZ-Kennung (z.B. mus43225): ").strip()
        bind_pass = getpass.getpass("Dein Passwort: ")
        search_user = input(f"Zu suchende RZ-Kennung [{bind_user}]: ").strip() or bind_user

    try:
        from ldap3 import Server, Connection, ALL, Tls, SUBTREE
        from ldap3.core.exceptions import LDAPException
        print("[OK] ldap3 importiert")
    except ImportError:
        print("[FEHLER] ldap3 nicht installiert!")
        print("         pip install ldap3")
        return

    # === Konfiguration ===
    LDAP_SERVER = "adldap.hs-regensburg.de"
    LDAP_PORT = 636
    LDAP_BASE_DN = "dc=hs-regensburg,dc=de"
    BIND_DN = f"{bind_user}@hs-regensburg.de"
    SEARCH_FILTER = f"(samAccountName={search_user})"
    ATTRIBUTES = [
        "givenName", "sn", "mail", "department",
        "samAccountName", "distinguishedName", "memberOf",
    ]

    print()
    print("=" * 60)
    print("LDAP-Verbindungstest HS Regensburg")
    print("=" * 60)
    print(f"  Server:   {LDAP_SERVER}:{LDAP_PORT} (LDAPS)")
    print(f"  Bind DN:  {BIND_DN}")
    print(f"  Base DN:  {LDAP_BASE_DN}")
    print(f"  Filter:   {SEARCH_FILTER}")
    print()

    # === Schritt 1: TLS ===
    print("[1/5] TLS-Konfiguration...")
    tls_config = None
    try:
        tls_config = Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLSv1_2)
        print("      OK (CERT_REQUIRED, TLSv1.2)")
    except Exception as e:
        print(f"      WARNUNG: Strikt TLS fehlgeschlagen: {e}")
        print("      Fallback auf CERT_NONE (nur zum Testen!)")
        tls_config = Tls(validate=ssl.CERT_NONE)

    # === Schritt 2: Server ===
    print("[2/5] Server-Objekt erstellen...")
    try:
        server = Server(
            LDAP_SERVER,
            port=LDAP_PORT,
            use_ssl=True,
            tls=tls_config,
            get_info=ALL,
            connect_timeout=10,
        )
        print(f"      OK")
    except Exception as e:
        print(f"      FEHLER: {e}")
        traceback.print_exc()
        return

    # === Schritt 3: Bind ===
    print(f"[3/5] Bind als {BIND_DN}...")
    conn = None
    try:
        conn = Connection(
            server,
            user=BIND_DN,
            password=bind_pass,
            auto_bind=True,
            raise_exceptions=True,
        )
        print(f"      OK – verbunden")
        print(f"      Result: {conn.result}")
        if server.info:
            naming = getattr(server.info, 'naming_contexts', None)
            if naming:
                print(f"      Naming Contexts: {naming}")
    except Exception as e:
        print(f"      FEHLER: {e}")
        traceback.print_exc()
        print()
        print("  Mögliche Ursachen:")
        print("  - Falsches Passwort")
        print("  - Account gesperrt")
        print("  - Nicht im Hochschulnetz / VPN nicht aktiv")
        print("  - Zertifikatsproblem")
        return

    # === Schritt 4: Suche ===
    print(f"[4/5] Suche: {SEARCH_FILTER} in {LDAP_BASE_DN}...")
    try:
        success = conn.search(
            search_base=LDAP_BASE_DN,
            search_filter=SEARCH_FILTER,
            search_scope=SUBTREE,
            attributes=ATTRIBUTES,
        )
        print(f"      Search success: {success}")
        print(f"      Result: {conn.result}")
        print(f"      Anzahl Ergebnisse: {len(conn.entries)}")
    except Exception as e:
        print(f"      FEHLER bei Suche: {e}")
        traceback.print_exc()

        # Retry mit kleinerem Scope
        print()
        print("      Versuche alternative Base DNs...")
        for alt_base in [
            "CN=Users,dc=hs-regensburg,dc=de",
            "OU=Users,dc=hs-regensburg,dc=de",
            "OU=Benutzer,dc=hs-regensburg,dc=de",
        ]:
            try:
                conn.search(
                    search_base=alt_base,
                    search_filter=SEARCH_FILTER,
                    search_scope=SUBTREE,
                    attributes=["samAccountName"],
                )
                print(f"      {alt_base}: {len(conn.entries)} Treffer")
            except Exception as e2:
                print(f"      {alt_base}: {e2}")
        conn.unbind()
        return

    # === Schritt 5: Ergebnisse ===
    print(f"[5/5] Ergebnisse:")
    print()
    if conn.entries:
        for i, entry in enumerate(conn.entries):
            print(f"  --- Eintrag {i + 1} ---")
            print(f"  DN: {entry.entry_dn}")
            for attr_name in ATTRIBUTES:
                try:
                    val = getattr(entry, attr_name, None)
                    if val is not None:
                        print(f"  {attr_name}: {val.value}")
                    else:
                        print(f"  {attr_name}: (nicht vorhanden)")
                except Exception:
                    print(f"  {attr_name}: (Fehler beim Lesen)")
            print()
    else:
        print("  KEINE ERGEBNISSE!")
        print()
        print("  Mögliche Ursachen:")
        print(f"  - RZ-Kennung '{search_user}' existiert nicht")
        print(f"  - Base DN '{LDAP_BASE_DN}' ist falsch/zu eingeschränkt")
        print(f"  - Bind-User hat keine Leserechte auf diesen Bereich")
        print()

        # Diagnostik: Eigenen Bind-User suchen
        if search_user != bind_user:
            print(f"  Versuche stattdessen den Bind-User ({bind_user}) zu suchen...")
            try:
                conn.search(
                    search_base=LDAP_BASE_DN,
                    search_filter=f"(samAccountName={bind_user})",
                    search_scope=SUBTREE,
                    attributes=["samAccountName", "distinguishedName"],
                )
                if conn.entries:
                    print(f"  -> Bind-User gefunden: {conn.entries[0].entry_dn}")
                    print(f"  -> Problem liegt am gesuchten User '{search_user}'")
                else:
                    print(f"  -> Auch Bind-User nicht gefunden!")
                    print(f"  -> Wahrscheinlich falscher Base DN oder fehlende Rechte")
            except Exception as e:
                print(f"  -> Fehler: {e}")

        # Diagnostik: Wildcard-Suche
        print()
        print("  Versuche Wildcard-Suche (erste 5 User)...")
        try:
            conn.search(
                search_base=LDAP_BASE_DN,
                search_filter="(samAccountName=*)",
                search_scope=SUBTREE,
                attributes=["samAccountName"],
                size_limit=5,
            )
            print(f"  -> {len(conn.entries)} Treffer:")
            for e in conn.entries:
                print(f"     {e.samAccountName.value} ({e.entry_dn})")
        except Exception as e:
            print(f"  -> Fehler: {e}")
            print(f"  -> Wildcard evtl. nicht erlaubt (normal bei AD)")

    conn.unbind()
    print()
    print("Fertig.")


if __name__ == "__main__":
    main()
