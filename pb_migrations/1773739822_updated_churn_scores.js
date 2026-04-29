/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_4056765257")

  // add field
  collection.fields.addAt(9, new Field({
    "hidden": false,
    "id": "json_churn_reasons",
    "maxSize": 2000000,
    "name": "churn_reasons",
    "presentable": false,
    "required": false,
    "system": false,
    "type": "json"
  }))

  // add field
  collection.fields.addAt(10, new Field({
    "hidden": false,
    "id": "json_upsell_reasons",
    "maxSize": 2000000,
    "name": "upsell_reasons",
    "presentable": false,
    "required": false,
    "system": false,
    "type": "json"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_4056765257")

  // remove field
  collection.fields.removeById("json_churn_reasons")

  // remove field
  collection.fields.removeById("json_upsell_reasons")

  return app.save(collection)
})
