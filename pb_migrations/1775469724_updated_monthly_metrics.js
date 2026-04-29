/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_1083440350")

  // add field
  collection.fields.addAt(1, new Field({
    "autogeneratePattern": "",
    "hidden": false,
    "id": "text2394296326",
    "max": 0,
    "min": 0,
    "name": "month",
    "pattern": "",
    "presentable": false,
    "primaryKey": false,
    "required": true,
    "system": false,
    "type": "text"
  }))

  // add field
  collection.fields.addAt(2, new Field({
    "hidden": false,
    "id": "number1643983414",
    "max": null,
    "min": null,
    "name": "total_conversations",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(3, new Field({
    "hidden": false,
    "id": "number3296521217",
    "max": null,
    "min": null,
    "name": "resolved_conversations",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(4, new Field({
    "hidden": false,
    "id": "number2389478872",
    "max": null,
    "min": null,
    "name": "resolution_rate_pct",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(5, new Field({
    "hidden": false,
    "id": "number3829805293",
    "max": null,
    "min": null,
    "name": "whatsapp_convos",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(6, new Field({
    "hidden": false,
    "id": "number2471908016",
    "max": null,
    "min": null,
    "name": "web_convos",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(7, new Field({
    "hidden": false,
    "id": "number2477655272",
    "max": null,
    "min": null,
    "name": "instagram_convos",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(8, new Field({
    "hidden": false,
    "id": "number809824115",
    "max": null,
    "min": null,
    "name": "active_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(9, new Field({
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
  collection.fields.addAt(10, new Field({
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
  collection.fields.addAt(11, new Field({
    "hidden": false,
    "id": "number3151898939",
    "max": null,
    "min": null,
    "name": "avg_frt_mins",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(12, new Field({
    "hidden": false,
    "id": "number818530634",
    "max": null,
    "min": null,
    "name": "avg_ttr_mins",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(13, new Field({
    "hidden": false,
    "id": "number3909370142",
    "max": null,
    "min": null,
    "name": "bot_conversations",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(14, new Field({
    "hidden": false,
    "id": "number2123859849",
    "max": null,
    "min": null,
    "name": "accounts_using_bots",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(15, new Field({
    "hidden": false,
    "id": "number2616294645",
    "max": null,
    "min": null,
    "name": "broadcast",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(16, new Field({
    "hidden": false,
    "id": "number18809873",
    "max": null,
    "min": null,
    "name": "bot",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(17, new Field({
    "hidden": false,
    "id": "number2902841359",
    "max": null,
    "min": null,
    "name": "api",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(18, new Field({
    "hidden": false,
    "id": "number2115105593",
    "max": null,
    "min": null,
    "name": "inbox",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(19, new Field({
    "hidden": false,
    "id": "number1384568619",
    "max": null,
    "min": null,
    "name": "sequence",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(20, new Field({
    "hidden": false,
    "id": "number4259933595",
    "max": null,
    "min": null,
    "name": "integration",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(21, new Field({
    "hidden": false,
    "id": "number3377271179",
    "max": null,
    "min": null,
    "name": "system",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(22, new Field({
    "hidden": false,
    "id": "number1983778347",
    "max": null,
    "min": null,
    "name": "broadcast_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(23, new Field({
    "hidden": false,
    "id": "number2167651462",
    "max": null,
    "min": null,
    "name": "bot_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(24, new Field({
    "hidden": false,
    "id": "number435377187",
    "max": null,
    "min": null,
    "name": "api_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(25, new Field({
    "hidden": false,
    "id": "number3892266279",
    "max": null,
    "min": null,
    "name": "inbox_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(26, new Field({
    "hidden": false,
    "id": "number1123339907",
    "max": null,
    "min": null,
    "name": "sequence_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(27, new Field({
    "hidden": false,
    "id": "number3625081670",
    "max": null,
    "min": null,
    "name": "integration_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(28, new Field({
    "hidden": false,
    "id": "number1222813478",
    "max": null,
    "min": null,
    "name": "whatsapp_channels",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(29, new Field({
    "hidden": false,
    "id": "number3830182747",
    "max": null,
    "min": null,
    "name": "web_channels",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(30, new Field({
    "hidden": false,
    "id": "number337760318",
    "max": null,
    "min": null,
    "name": "instagram_channels",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(31, new Field({
    "hidden": false,
    "id": "number4203327252",
    "max": null,
    "min": null,
    "name": "accounts_with_channels",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(32, new Field({
    "hidden": false,
    "id": "number2714370477",
    "max": null,
    "min": null,
    "name": "zoho_bulk",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(33, new Field({
    "hidden": false,
    "id": "number1479562208",
    "max": null,
    "min": null,
    "name": "zoho_widget",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(34, new Field({
    "hidden": false,
    "id": "number1282894148",
    "max": null,
    "min": null,
    "name": "hubspot_workflow",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(35, new Field({
    "hidden": false,
    "id": "number3596784512",
    "max": null,
    "min": null,
    "name": "hubspot_widget",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(36, new Field({
    "hidden": false,
    "id": "number2766066074",
    "max": null,
    "min": null,
    "name": "pipedrive_widget",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(37, new Field({
    "hidden": false,
    "id": "number501434555",
    "max": null,
    "min": null,
    "name": "zoho_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(38, new Field({
    "hidden": false,
    "id": "number3816452094",
    "max": null,
    "min": null,
    "name": "hubspot_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(39, new Field({
    "hidden": false,
    "id": "number3414542117",
    "max": null,
    "min": null,
    "name": "pipedrive_accounts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(40, new Field({
    "hidden": false,
    "id": "number1948883295",
    "max": null,
    "min": null,
    "name": "new_contacts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(41, new Field({
    "hidden": false,
    "id": "number1435419762",
    "max": null,
    "min": null,
    "name": "convos_mom",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(42, new Field({
    "hidden": false,
    "id": "number2883696569",
    "max": null,
    "min": null,
    "name": "accounts_mom",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(43, new Field({
    "hidden": false,
    "id": "number1035297134",
    "max": null,
    "min": null,
    "name": "frt_mom",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(44, new Field({
    "hidden": false,
    "id": "number1991398456",
    "max": null,
    "min": null,
    "name": "bot_mom",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(45, new Field({
    "hidden": false,
    "id": "number873133705",
    "max": null,
    "min": null,
    "name": "sequence_mom",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(46, new Field({
    "hidden": false,
    "id": "number2775195527",
    "max": null,
    "min": null,
    "name": "broadcast_mom",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  // add field
  collection.fields.addAt(47, new Field({
    "hidden": false,
    "id": "number1371620435",
    "max": null,
    "min": null,
    "name": "new_contacts_mom",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_1083440350")

  // remove field
  collection.fields.removeById("text2394296326")

  // remove field
  collection.fields.removeById("number1643983414")

  // remove field
  collection.fields.removeById("number3296521217")

  // remove field
  collection.fields.removeById("number2389478872")

  // remove field
  collection.fields.removeById("number3829805293")

  // remove field
  collection.fields.removeById("number2471908016")

  // remove field
  collection.fields.removeById("number2477655272")

  // remove field
  collection.fields.removeById("number809824115")

  // remove field
  collection.fields.removeById("number179270265")

  // remove field
  collection.fields.removeById("number2682217005")

  // remove field
  collection.fields.removeById("number3151898939")

  // remove field
  collection.fields.removeById("number818530634")

  // remove field
  collection.fields.removeById("number3909370142")

  // remove field
  collection.fields.removeById("number2123859849")

  // remove field
  collection.fields.removeById("number2616294645")

  // remove field
  collection.fields.removeById("number18809873")

  // remove field
  collection.fields.removeById("number2902841359")

  // remove field
  collection.fields.removeById("number2115105593")

  // remove field
  collection.fields.removeById("number1384568619")

  // remove field
  collection.fields.removeById("number4259933595")

  // remove field
  collection.fields.removeById("number3377271179")

  // remove field
  collection.fields.removeById("number1983778347")

  // remove field
  collection.fields.removeById("number2167651462")

  // remove field
  collection.fields.removeById("number435377187")

  // remove field
  collection.fields.removeById("number3892266279")

  // remove field
  collection.fields.removeById("number1123339907")

  // remove field
  collection.fields.removeById("number3625081670")

  // remove field
  collection.fields.removeById("number1222813478")

  // remove field
  collection.fields.removeById("number3830182747")

  // remove field
  collection.fields.removeById("number337760318")

  // remove field
  collection.fields.removeById("number4203327252")

  // remove field
  collection.fields.removeById("number2714370477")

  // remove field
  collection.fields.removeById("number1479562208")

  // remove field
  collection.fields.removeById("number1282894148")

  // remove field
  collection.fields.removeById("number3596784512")

  // remove field
  collection.fields.removeById("number2766066074")

  // remove field
  collection.fields.removeById("number501434555")

  // remove field
  collection.fields.removeById("number3816452094")

  // remove field
  collection.fields.removeById("number3414542117")

  // remove field
  collection.fields.removeById("number1948883295")

  // remove field
  collection.fields.removeById("number1435419762")

  // remove field
  collection.fields.removeById("number2883696569")

  // remove field
  collection.fields.removeById("number1035297134")

  // remove field
  collection.fields.removeById("number1991398456")

  // remove field
  collection.fields.removeById("number873133705")

  // remove field
  collection.fields.removeById("number2775195527")

  // remove field
  collection.fields.removeById("number1371620435")

  return app.save(collection)
})
