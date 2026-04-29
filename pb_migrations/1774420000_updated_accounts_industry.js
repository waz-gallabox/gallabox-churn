/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("accounts");
  collection.fields.add(new Field({ "id": "text_industry", "name": "industry", "type": "text", "required": false }));
  app.save(collection);
}, (app) => {
  const collection = app.findCollectionByNameOrId("accounts");
  collection.fields.removeById("text_industry");
  app.save(collection);
});
