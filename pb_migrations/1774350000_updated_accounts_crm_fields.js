/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("accounts");

  collection.fields.add(new Field({
    "id": "text_lead_owner",
    "name": "lead_owner",
    "type": "text",
    "required": false,
  }));
  collection.fields.add(new Field({
    "id": "text_lead_owner_email",
    "name": "lead_owner_email",
    "type": "text",
    "required": false,
  }));
  collection.fields.add(new Field({
    "id": "text_kam",
    "name": "kam",
    "type": "text",
    "required": false,
  }));
  collection.fields.add(new Field({
    "id": "text_crm_account_id",
    "name": "crm_account_id",
    "type": "text",
    "required": false,
  }));

  app.save(collection);
}, (app) => {
  const collection = app.findCollectionByNameOrId("accounts");
  collection.fields.removeById("text_lead_owner");
  collection.fields.removeById("text_lead_owner_email");
  collection.fields.removeById("text_kam");
  collection.fields.removeById("text_crm_account_id");
  app.save(collection);
});
