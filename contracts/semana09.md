# Semana 9: contrato de aceptación

El catálogo y el checkout son de demostración. No introduzcas datos personales ni dinero real.

El comando de smoke comprueba arranque y compra básica; no equivale a aprobar Semana9. El evaluador docente usa la misma API de negocio y datos de prueba aislados.

Se exige: entradas conforme al contrato JSON (cantidad entera estricta,1..5); pedidos persistentes; idempotencia sin efectos duplicados; inventario consistente; CloudEvents válidos con identidad y datos completos; notificación eventual; respuesta HTTP independiente de la lentitud de una notificación. Pueden emplearse IA y herramientas, pero no eliminar funciones ni falsificar respuestas de las pruebas.

La evaluación remota usa tráfico pequeño y compara condiciones de la misma instancia, no promete rendimiento absoluto de Internet. Un problema de túnel/red se informa como inconcluso. Los cambios internos son libres mientras se conserven endpoints, esquemas, claves y controles de acceso. La salida del test acredita comportamiento bajo esas condiciones, no prueba por sí sola una arquitectura específica. Las rutas de diagnóstico también viven en la máquina del alumno y no constituyen una atestación independiente de Redis o de la estructura interna; el docente puede contrastarlas con el código y una variante de prueba.

El header Idempotency-Key es obligatorio en POST /api/v1/orders. Mismo cuerpo y clave: mismo201 y snapshot original. Otro cuerpo y misma clave:409. Agotamiento:409 OUT_OF_STOCK. Payload inválido:422 VALIDATION_ERROR. Producto inexistente:404 NOT_FOUND.

La inspección de pruebas /_lab/* requiere X-Lab-Key; X-Lab-Run se acepta solo con esa clave y un dataset válido. No elimines autenticación, aislamiento ni límites para pasar una prueba. No pongas claves en frontend, commits, URLs o capturas.

Extensiones10–15 se anunciarán por semana. No se exigen ahora nuevas nubes, microservicios, pagos reales ni LLM.
