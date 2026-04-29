/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = new Collection({
    "createRule": null,
    "deleteRule": null,
    "fields": [
      {
        "autogeneratePattern": "[a-z0-9]{15}",
        "hidden": false,
        "id": "text3208210256",
        "max": 15,
        "min": 15,
        "name": "id",
        "pattern": "^[a-z0-9]+$",
        "presentable": false,
        "primaryKey": true,
        "required": true,
        "system": true,
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_account_id",
        "max": 0,
        "min": 0,
        "name": "account_id",
        "pattern": "",
        "presentable": false,
        "primaryKey": false,
        "required": true,
        "system": false,
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_ticket_id",
        "max": 0,
        "min": 0,
        "name": "ticket_id",
        "pattern": "",
        "presentable": false,
        "primaryKey": false,
        "required": true,
        "system": false,
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_ticket_number",
        "name": "ticket_number",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_subject",
        "name": "subject",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_status",
        "name": "status",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_status_type",
        "name": "status_type",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_category",
        "name": "category",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_sub_category",
        "name": "sub_category",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_priority",
        "name": "priority",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "bool_is_escalated",
        "name": "is_escalated",
        "type": "bool"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "bool_is_overdue",
        "name": "is_overdue",
        "type": "bool"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "bool_is_churn_ticket",
        "name": "is_churn_ticket",
        "type": "bool"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "num_thread_count",
        "name": "thread_count",
        "type": "number"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_created_time",
        "name": "created_time",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_closed_time",
        "name": "closed_time",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_web_url",
        "name": "web_url",
        "type": "text"
      },
      {
        "autogeneratePattern": "",
        "hidden": false,
        "id": "text_synced_at",
        "name": "synced_at",
        "type": "text"
      }
    ],
    "indexes": [
      "CREATE INDEX idx_zoho_tickets_account ON zoho_tickets (account_id)",
      "CREATE UNIQUE INDEX idx_zoho_tickets_ticket_id ON zoho_tickets (ticket_id)"
    ],
    "listRule": "",
    "name": "zoho_tickets",
    "type": "base",
    "updateRule": null,
    "viewRule": ""
  });
  app.save(collection);
}, (app) => {
  const collection = app.findCollectionByNameOrId("zoho_tickets");
  app.delete(collection);
});
