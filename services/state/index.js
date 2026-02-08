const { Client } = require("pg");
const crypto = require("crypto");
const players = require("./players");
const devices = require("./devices");
const deviceAssignments = require("./device_assignments");
const veranstalter = require("./veranstalter");
const betriebsstaetten = require("./betriebsstaetten");

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

const activeAssignments = deviceAssignments.map((assignment) => ({
    ...assignment,
    valid_to: null
}));

const betriebsstaetteById = new Map(
    betriebsstaetten.map((entry) => [entry.betriebsstaette_id, entry])
);

async function ensureSchemaAndSeed() {
    await client.query("CREATE SCHEMA IF NOT EXISTS dataplatform");

    await client.query(`
        CREATE TABLE IF NOT EXISTS dataplatform.veranstalter (
            id uuid PRIMARY KEY,
            name text NOT NULL,
            region text
        )
    `);

    await client.query(`
        CREATE TABLE IF NOT EXISTS dataplatform.betriebsstaette (
            id uuid PRIMARY KEY,
            veranstalter_id uuid NOT NULL,
            name text NOT NULL,
            city text,
            FOREIGN KEY (veranstalter_id) REFERENCES dataplatform.veranstalter(id)
        )
    `);

    await client.query(`
        CREATE TABLE IF NOT EXISTS dataplatform.geraet (
            id uuid PRIMARY KEY,
            serial text,
            model text
        )
    `);

    await client.query(`
        CREATE TABLE IF NOT EXISTS dataplatform.player (
            id uuid PRIMARY KEY,
            vorname text NOT NULL,
            nachname text NOT NULL,
            geburtsdatum date
        )
    `);

    await client.query(`
        CREATE TABLE IF NOT EXISTS dataplatform.device_assignment (
            id uuid PRIMARY KEY,
            geraet_id uuid NOT NULL,
            veranstalter_id uuid NOT NULL,
            betriebsstaette_id uuid NOT NULL,
            valid_from timestamptz NOT NULL,
            valid_to timestamptz,
            FOREIGN KEY (geraet_id) REFERENCES dataplatform.geraet(id),
            FOREIGN KEY (veranstalter_id) REFERENCES dataplatform.veranstalter(id),
            FOREIGN KEY (betriebsstaette_id) REFERENCES dataplatform.betriebsstaette(id)
        )
    `);

    await client.query(`
        CREATE TABLE IF NOT EXISTS dataplatform.status_abfrage (
            unique_identifier uuid PRIMARY KEY,
            status_ts timestamptz NOT NULL,
            veranstalter_id uuid NOT NULL,
            betriebsstaette_id uuid NOT NULL,
            geraete_id uuid NOT NULL,
            player_id uuid NOT NULL,
            vorname text NOT NULL,
            nachname text NOT NULL,
            geburtsdatum date,
            FOREIGN KEY (veranstalter_id) REFERENCES dataplatform.veranstalter(id),
            FOREIGN KEY (betriebsstaette_id) REFERENCES dataplatform.betriebsstaette(id),
            FOREIGN KEY (geraete_id) REFERENCES dataplatform.geraet(id),
            FOREIGN KEY (player_id) REFERENCES dataplatform.player(id)
        )
    `);

    for (const entry of veranstalter) {
        await client.query(
            `
            INSERT INTO dataplatform.veranstalter (id, name, region)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO NOTHING
        `,
            [entry.veranstalter_id, entry.name, entry.region]
        );
    }

    for (const entry of betriebsstaetten) {
        await client.query(
            `
            INSERT INTO dataplatform.betriebsstaette (id, veranstalter_id, name, city)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO NOTHING
        `,
            [entry.betriebsstaette_id, entry.veranstalter_id, entry.name, entry.city]
        );
    }

    for (const entry of devices) {
        await client.query(
            `
            INSERT INTO dataplatform.geraet (id, serial, model)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO NOTHING
        `,
            [entry.geraete_id, entry.serial, entry.model]
        );
    }

    for (const entry of players) {
        await client.query(
            `
            INSERT INTO dataplatform.player (id, vorname, nachname, geburtsdatum)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO NOTHING
        `,
            [entry.player_id, entry.vorname, entry.nachname, entry.geburtsdatum]
        );
    }

    for (const entry of activeAssignments) {
        await client.query(
            `
            INSERT INTO dataplatform.device_assignment (
                id, geraet_id, veranstalter_id, betriebsstaette_id, valid_from, valid_to
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO NOTHING
        `,
            [
                entry.assignment_id,
                entry.geraete_id,
                entry.veranstalter_id,
                entry.betriebsstaette_id,
                entry.valid_from,
                entry.valid_to
            ]
        );
    }
}

async function maybeReassignDevice() {
    if (Math.random() > 0.1) {
        return;
    }

    const current = chooseRandom(activeAssignments);
    const options = betriebsstaetten.filter(
        (entry) => entry.betriebsstaette_id !== current.betriebsstaette_id
    );

    if (options.length === 0) {
        return;
    }

    const next = chooseRandom(options);
    const now = new Date().toISOString();

    current.valid_to = now;

    await client.query(
        `
        UPDATE dataplatform.device_assignment
        SET valid_to = $1
        WHERE id = $2
    `,
        [now, current.assignment_id]
    );

    const newAssignment = {
        assignment_id: crypto.randomUUID(),
        geraete_id: current.geraete_id,
        veranstalter_id: next.veranstalter_id,
        betriebsstaette_id: next.betriebsstaette_id,
        valid_from: now,
        valid_to: null
    };

    activeAssignments.push(newAssignment);

    await client.query(
        `
        INSERT INTO dataplatform.device_assignment (
            id, geraet_id, veranstalter_id, betriebsstaette_id, valid_from, valid_to
        ) VALUES ($1, $2, $3, $4, $5, $6)
    `,
        [
            newAssignment.assignment_id,
            newAssignment.geraete_id,
            newAssignment.veranstalter_id,
            newAssignment.betriebsstaette_id,
            newAssignment.valid_from,
            newAssignment.valid_to
        ]
    );

    const fromBetrieb = betriebsstaetteById.get(current.betriebsstaette_id);
    const toBetrieb = betriebsstaetteById.get(next.betriebsstaette_id);

    console.log(
        `[${new Date().toISOString()}] Device moved ${current.geraete_id} from ` +
        `${fromBetrieb ? fromBetrieb.name : current.betriebsstaette_id} to ` +
        `${toBetrieb ? toBetrieb.name : next.betriebsstaette_id}`
    );
}

async function insertStatus() {
    const player = chooseRandom(players);
    const assignments = activeAssignments.filter((entry) => entry.valid_to === null);
    const assignment = chooseRandom(assignments);

    const query = `
    INSERT INTO dataplatform.status_abfrage (
      unique_identifier,
      status_ts,
      veranstalter_id,
      betriebsstaette_id,
      geraete_id,
      player_id,
      vorname,
      nachname,
      geburtsdatum
    ) VALUES (
      $1, $2, $3, $4, $5, $6, $7, $8, $9
    )
  `;

    const values = [
        crypto.randomUUID(),
        new Date().toISOString(),
        assignment.veranstalter_id,
        assignment.betriebsstaette_id,
        assignment.geraete_id,
        player.player_id,
        player.vorname,
        player.nachname,
        player.geburtsdatum
    ];

    try {
        await client.query(query, values);
        console.log(
            `[${new Date().toISOString()}] Inserted status for ${player.vorname} ${player.nachname}`
        );
        await maybeReassignDevice();
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
    console.log("Connected to Postgres, ensuring schema and seed data...");
    await ensureSchemaAndSeed();
    console.log("Starting status generator...");

    // alle 10 Sekunden ein Insert
    setInterval(insertStatus, 10 * 1000);
}

main().catch(err => {
    console.error("Fatal error:", err);
    process.exit(1);
});
