/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");
  collection.fields.add(new Field({ "id": "num_total_contacts", "name": "total_contacts", "type": "number", "required": false }));
  app.save(collection);
}, (app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");
  collection.fields.removeById("num_total_contacts");
  app.save(collection);
});
