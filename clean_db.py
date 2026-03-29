import sqlite3

conn = sqlite3.connect('trades.db')

# Vérifier d'abord
count = conn.execute("SELECT COUNT(*) FROM trades WHERE timestamp < '2026-03-23'").fetchone()[0]
print(f"Trades à supprimer: {count}")

first = conn.execute("SELECT MIN(timestamp) FROM trades").fetchone()[0]
print(f"Trade le plus ancien: {first}")

confirm = input("Confirmer la suppression ? (oui/non): ")

if confirm.lower() == "oui":
    conn.execute("DELETE FROM trades WHERE timestamp < '2026-03-23'")
    conn.commit()
    print("✅ Supprimé avec succès")
    remaining = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    print(f"Trades restants: {remaining}")
else:
    print("Annulé.")

conn.close()