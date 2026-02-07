const { Client } = require("pg");
const players = require("./players");

// Postgres config über Environment Vars
const client = new Client({
    host: process.env.PG_HOST,
    port: parseInt(process.env.PG_PORT || "5432", 10),
    database: process.env.PG_DATABASE,
    user: process.env.PG_USER,
    password: process.env.PG_PASSWORD
});

// Random Element Helper
function chooseRandom(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
}

async function insertStatus() {
    const player = chooseRandom(players);

    const query = `
    INSERT INTO dataplatform.status_abfrage (
      unique_identifier,
      veranstalter_id,
      betriebsstaette_id,
      geraete_id,
      vorname,
      nachname,
      geburtsdatum
    ) VALUES (
      gen_random_uuid(),
      $1, $2, $3,
      $4, $5, $6
    )
  `;

    const values = [
        player.veranstalter_id,
        player.betriebsstaette_id,
        player.geraete_id,
        player.vorname,
        player.nachname,
        player.geburtsdatum
    ];

    try {
        await client.query(query, values);
        console.log(`[${new Date().toISOString()}] Inserted status for ${player.vorname} ${player.nachname}`);
    } catch (err) {
        console.error("Error inserting status:", err);
    }
}

async function main() {
    await client.connect();
    console.log("Connected to Postgres, starting status generator...");

    // alle 10 Sekunden ein Insert
    setInterval(insertStatus, 10 * 1000);
}

main().catch(err => {
    console.error("Fatal error:", err);
    process.exit(1);
});
