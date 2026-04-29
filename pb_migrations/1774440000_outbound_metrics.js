/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");

  const newFields = [
    { id: "num_broadcasts_30d",     name: "broadcasts_30d",     type: "number" },
    { id: "num_sequences_active",   name: "sequences_active",   type: "number" },
    { id: "num_cta_leads_captured", name: "cta_leads_captured", type: "number" },
  ];

  for (const f of newFields) {
    collection.fields.add(new Field({ ...f, required: false }));
  }
  app.save(collection);
  console.log("Added broadcasts_30d, sequences_active, cta_leads_captured");
}, (app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");
  ["num_broadcasts_30d", "num_sequences_active", "num_cta_leads_captured"].forEach(id => {
    collection.fields.removeById(id);
  });
  app.save(collection);
});
