Vamos a obtener los datos de previsión meteorológia a través de la API de AEMET. La api key está definida en el .env con la varible AEMET_API_KEY.
Necesitamos consultar los datos solo de municipios/zonas donde tengamos una parcela a la que estemos haciendo seguimiento (algun usuario la ha "reclamado" a través de la UI).
Los datos los guardaremos en una base de datos a nivel de municipio/zona, asi solo tenemos un registro aunque tengamos varias parcelas en la misma zona.
Necesitamos guardar la previsión para el máximo de dias que nos devuelva la API. 

La documentación de la API está en este link: https://opendata.aemet.es/dist/index.html?

Necesito definir como guardar estos datos en GCP, teniendo en cuenta que para el modelo de IA no solo consultaré la previsión, sino el histórico de los últimos 40 dias, que todavia está por definir de donde se obtendrán. 

