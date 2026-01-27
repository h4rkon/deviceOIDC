const express = require("express");

const app = express();
app.use(express.json({ limit: "256kb" }));

app.get("/healthz", (_req, res) => res.status(200).send("ok"));

app.post("/hello", (req, res) => {
    res.json({
        ok: true,
        ts: new Date().toISOString(),
        noise: "meaningless-shit",
        youSent: req.body ?? null
    });
});

const port = Number(process.env.PORT || 3000);
app.listen(port, () => console.log(`hello service listening on :${port}`));
