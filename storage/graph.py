from __future__ import annotations


class GraphMixin:
    def edge_decay(self, factor=0.9, planet=None):
        c = self.storage.connection.cursor()
        if planet:
            ids = [r["id"] for r in c.execute("SELECT id FROM notes WHERE topic=?", (self.normalize_topic(planet),))]
            if not ids:
                return {"decayed": 0, "factor": factor, "message": "No notes in planet"}
            ph = ",".join("?" for _ in ids)
            n = c.execute(
                f"UPDATE note_links SET weight=ROUND(weight * ?, 3), updated_at=? WHERE (from_note_id IN ({ph}) OR to_note_id IN ({ph})) AND source='auto'",
                (factor, self._now(), *ids, *ids),
            ).rowcount
        else:
            n = c.execute("UPDATE note_links SET weight=ROUND(weight * ?, 3), updated_at=? WHERE source='auto'", (factor, self._now())).rowcount
        self.storage.connection.commit()
        return {"decayed": n, "factor": factor}

    def edge_prune(self, threshold=0.05, planet=None):
        c = self.storage.connection.cursor()
        if planet:
            ids = [r["id"] for r in c.execute("SELECT id FROM notes WHERE topic=?", (self.normalize_topic(planet),))]
            if not ids:
                return {"pruned": 0, "threshold": threshold, "message": "No notes in planet"}
            ph = ",".join("?" for _ in ids)
            n = c.execute(
                f"DELETE FROM note_links WHERE weight < ? AND source='auto' AND (from_note_id IN ({ph}) OR to_note_id IN ({ph}))", (threshold, *ids, *ids)
            ).rowcount
        else:
            n = c.execute("DELETE FROM note_links WHERE weight < ? AND source='auto'", (threshold,)).rowcount
        self.storage.connection.commit()
        return {"pruned": n, "threshold": threshold}

    def edge_maintain(self, planet=None, decay_factor=None, prune_threshold=None):
        if decay_factor is None and prune_threshold is None:
            return "Error: at least one of decay_factor or prune_threshold must be provided."
        out = []
        if decay_factor is not None:
            r = self.edge_decay(decay_factor, planet)
            out.append(f"Decayed {r['decayed']} edge(s) by factor {r['factor']}.")
        if prune_threshold is not None:
            r = self.edge_prune(prune_threshold, planet)
            out.append(f"Pruned {r['pruned']} edge(s) below threshold {r['threshold']}.")
        return " ".join(out)
