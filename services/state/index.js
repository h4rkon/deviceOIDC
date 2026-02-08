const { Client } = require("pg");
const players = require("./players");
const devices = require("./devices");

// Postgres config über Environment Vars
const client = new Client({
    host: process.env.POSTGRES_HOST,
    port: parseInt(process.env.POSTGRES_PORT || "5432", 10),
    database: process.env.POSTGRES_DB,
    user: process.env.POSTGRES_USER,
    password: process.env.POSTGRES_PASSWORD
});

// Random Element Helper
function chooseRandom(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
}

async function insertStatus() {
    const player = chooseRandom(players);
    const device = chooseRandom(devices);

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
        device.veranstalter_id,
        device.betriebsstaette_id,
        device.geraete_id,
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
    console.log("Postgres config:", {
        host: process.env.POSTGRES_HOST,
        port: process.env.POSTGRES_PORT || "5432",
        database: process.env.POSTGRES_DB,
        user: process.env.POSTGRES_USER
    });
    await client.connect();
    console.log("Connected to Postgres, starting status generator...");

    // alle 10 Sekunden ein Insert
    setInterval(insertStatus, 10 * 1000);
}

main().catch(err => {
    console.error("Fatal error:", err);
    process.exit(1);
});
