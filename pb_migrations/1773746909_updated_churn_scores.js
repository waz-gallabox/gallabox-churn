/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_4056765257")

  // add field
  collection.fields.addAt(11, new Field({
    "hidden": false,
    "id": "number1393443242",
    "max": null,
    "min": null,
    "name": "convos_7d",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(12, new Field({
    "hidden": false,
    "id": "number2001944311",
    "max": null,
    "min": null,
    "name": "convos_30d",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(13, new Field({
    "hidden": false,
    "id": "number2175283072",
    "max": null,
    "min": null,
    "name": "messages_7d",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(14, new Field({
    "hidden": false,
    "id": "number1222025507",
    "max": null,
    "min": null,
    "name": "avg_msgs_per_convo",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(15, new Field({
    "hidden": false,
    "id": "number1122635491",
    "max": null,
    "min": null,
    "name": "bot_ratio",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(16, new Field({
    "hidden": false,
    "id": "number253879262",
    "max": null,
    "min": null,
    "name": "resolution_rate",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(17, new Field({
    "hidden": false,
    "id": "number3081539262",
    "max": null,
    "min": null,
    "name": "avg_frt_secs",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(18, new Field({
    "hidden": false,
    "id": "number179270265",
    "max": null,
    "min": null,
    "name": "active_agents",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(19, new Field({
    "hidden": false,
    "id": "number2682217005",
    "max": null,
    "min": null,
    "name": "active_bots",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(20, new Field({
    "hidden": false,
    "id": "number1307307527",
    "max": null,
    "min": null,
    "name": "total_channels",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(21, new Field({
    "hidden": false,
    "id": "number3642333503",
    "max": null,
    "min": null,
    "name": "trend_consistency",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_4056765257")

  // remove field
  collection.fields.removeById("number1393443242")

  // remove field
  collection.fields.removeById("number2001944311")

  // remove field
  collection.fields.removeById("number2175283072")

  // remove field
  collection.fields.removeById("number1222025507")

  // remove field
  collection.fields.removeById("number1122635491")

  // remove field
  collection.fields.removeById("number253879262")

  // remove field
  collection.fields.removeById("number3081539262")

  // remove field
  collection.fields.removeById("number179270265")

  // remove field
  collection.fields.removeById("number2682217005")

  // remove field
  collection.fields.removeById("number1307307527")

  // remove field
  collection.fields.removeById("number3642333503")

  return app.save(collection)
})
