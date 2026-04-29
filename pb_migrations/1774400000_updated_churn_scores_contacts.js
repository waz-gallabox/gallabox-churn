/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");

  collection.fields.add(new Field({ "id": "num_convos_90d",        "name": "convos_90d",        "type": "number", "required": false }));
  collection.fields.add(new Field({ "id": "num_new_contacts_7d",   "name": "new_contacts_7d",   "type": "number", "required": false }));
  collection.fields.add(new Field({ "id": "num_new_contacts_30d",  "name": "new_contacts_30d",  "type": "number", "required": false }));
  collection.fields.add(new Field({ "id": "num_new_contacts_90d",  "name": "new_contacts_90d",  "type": "number", "required": false }));

  app.save(collection);
}, (app) => {
  const collection = app.findCollectionByNameOrId("churn_scores");
  collection.fields.removeById("num_convos_90d");
  collection.fields.removeById("num_new_contacts_7d");
  collection.fields.removeById("num_new_contacts_30d");
  collection.fields.removeById("num_new_contacts_90d");
  app.save(collection);
});
