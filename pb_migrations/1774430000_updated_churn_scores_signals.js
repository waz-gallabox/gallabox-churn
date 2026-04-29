/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");
  const fields = [
    { id: "num_open_backlog_pct",      name: "open_backlog_pct" },
    { id: "num_contact_initiated_pct", name: "contact_initiated_pct" },
    { id: "num_marketing_msgs_30d",    name: "marketing_msgs_30d" },
    { id: "num_utility_msgs_30d",      name: "utility_msgs_30d" },
    { id: "num_service_msgs_30d",      name: "service_msgs_30d" },
    { id: "num_template_sends_30d",    name: "template_sends_30d" },
    { id: "num_broadcasts_30d",        name: "broadcasts_30d" },
    { id: "num_sequences_active",      name: "sequences_active" },
    { id: "num_cta_leads_captured",    name: "cta_leads_captured" },
  ];
  for (const f of fields) {
    collection.fields.add(new Field({ ...f, type: "number", required: false }));
  }
  app.save(collection);
}, (app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");
  for (const id of ["num_open_backlog_pct","num_contact_initiated_pct","num_marketing_msgs_30d","num_utility_msgs_30d","num_service_msgs_30d","num_template_sends_30d","num_broadcasts_30d","num_sequences_active","num_cta_leads_captured"]) {
    collection.fields.removeById(id);
  }
  app.save(collection);
});
