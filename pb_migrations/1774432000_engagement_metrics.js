/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");
  
  const newFields = [
    { id: "num_total_msgs_30d",      name: "total_msgs_30d",      type: "number" },
    { id: "num_proactive_msgs_30d",  name: "proactive_msgs_30d",  type: "number" },
  ];

  for (const f of newFields) {
    collection.fields.add(new Field({ ...f, required: false }));
  }
  app.save(collection);
  console.log("Added total_msgs_30d and proactive_msgs_30d");
}, (app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");
  ["num_total_msgs_30d", "num_proactive_msgs_30d"].forEach(id => {
    collection.fields.removeById(id);
  });
  app.save(collection);
});
