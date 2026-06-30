# EDA
## Fuentes de datos

- **Periodo temporal:** 1982–2022 (41 años)
- **Resolución espacial:** 0.5º x 0.5º (360 x 720 celdas globales)
- **Variables climáticas (anuales):**

  - `t2m` – Temperatura del aire a 2 m
  - `d2m` – Temperatura de punto de rocío a 2 m
  - `tp` – Precipitación total
  - `pev` – Evapotranspiración potencial
  - `vpd` – Déficit de presión de vapor
  - `ssrd` – Radiación solar en superficie
  - `swvl1`, `swvl2`, `swvl3` – Humedad de suelo en distintas capas
  - `swc_sub` – Humedad de suelo integrada/subsuperficial
  - `tcc` – Nubosidad total
  - `u10`,`v10` (componentes del viento 10m)
  - `wind_speed` (calculada como √(u10² + v10²))
  - `spei` 01, 02, 03, 06, 09, 12,  24

- **Variable de vegetación:**

  - `lai` – Leaf Area Index (LAI), integrado anualmente a partir de los datos mensuales.Predictores


## Dimensiones, estructura

* Dims: `time`, `latitude`, `longitude`, `variable`

**Resolución espacial:** 0.5° × 0.5°
   * `latitude` en `[−90.0, 89.5]` (paso regular).
   * `longitude` en `[−180.0, 179.5]` (paso regular).

**Resolución temporal:**  1982-01-01 - 2022-01-01 (41 años)
   * Dimensiones annual:   `(time=41, latitude=360, longitude=720)`
   * Dimensiones monthly:   `(time=492, latitude=360, longitude=720)`

## Missing values
* **spei** NaN ratio: 74 % --> Alrededor del 76% del planeta es océano, donde SPEI se define como NaN.
* **LAI** El producto original no usaba NaN, sino valores centinela (p.ej. -255, 255) para “no data”. Ademas, la mayor parte del planeta tiene LAI = 0. constant_ratio ≈ 75 %

→ **Se crea mascara de tierra (land_mask.nc) para diferenciar tierra/agua basada en LAI**

## Continuidad temporal

* **wind** - Smooth segments: ['1995', '2018', '2022']
* **lai** - Smooth segments: ['1985', '1991']
* **spei**
    - Smooth segments:
        -  spei01 - ['2002']
        -  spei02 - ['1999', '2002']
        -  spei03 - ['1984', '1985', '1997', '2020']
        -  spei06 - ['2020']
        -  spei09 - ['1999', '2008', '2009']
        -  spei12 - ['1986']
        -  spei24 - ['1992', '2000', '2019']

* **d2m** - Smooth segments: ['2018']
* **v10** - Smooth segments: ['2009]
* **tp** - Smooth segments: ['1987', '1988']
* **pev** - Smooth segments: ['2020]
* **tcc** - Smooth segments: ['1984', '1990', '2014']
* **ssrd** - Smooth segments: ['2022']
* **u10** - Smooth segments: ['2018]
* **vpd** - Smooth segments: ['2020]
* **t2m** - Smooth segments: ['1987', '1994', '1997', '2012']

# Estadísticas descriptiva
## Stats por variable
### Datos `reales`

| variable | valid_pixels | nan % | zero % | min    | max    | mean   | std   | p01    | p05    | p50       | p95       | p99       |
|:--------:|:------------:|:-----:|:------:|:------:|:------:|:------:|:-----:|:------:|:------:|:---------:|:---------:|:---------:|
| wind     | 10627200     | 0.00  | 0.00   | 0.06   | 15.55  | 3.88   | 2.18  | 0.52   | 0.92   | 3.47      | 7.75      | 9.09      |
| lai      | 2635849      | 75.20 | 0.09   | 0.00   | 251.81 | 41.63  | 46.55 | 1.00   | 1.00   | 28.42     | 147.00    | 230.81    |
| spei01   | 2726541      | 74.34 | 0.00   | -2.92  | 2.31   | -0.05  | 0.43  | -1.16  | -0.78  | -0.03     | 0.63      | 0.91      |
| d2m      | 10627198     | 0.00  | 0.00   | 214.16 | 298.80 | 274.07 | 19.20 | 220.47 | 229.91 | 277.46    | 296.42    | 297.05    |
| swvl3    | 10627200     | 0.00  | 0.00   | 0.00   | 0.76   | 0.09   | 0.14  | 0.00   | 0.00   | 0.00      | 0.36      | 0.45      |
| spei03   | 2726541      | 74.34 | 0.00   | -4.49  | 2.94   | -0.06  | 0.61  | -1.53  | -1.09  | -0.05     | 0.93      | 1.32      |
| v10      | 10627200     | 0.00  | 0.00   | -8.56  | 15.47  | 0.19   | 2.03  | -5.35  | -2.73  | 0.01      | 4.10      | 6.59      |
| swvl1    | 10627200     | 0.00  | 0.00   | -0.00  | 0.76   | 0.09   | 0.14  | 0.00   | 0.00   | 0.00      | 0.37      | 0.45      |
| spei06   | 2726541      | 74.34 | 0.00   | -4.93  | 4.23   | -0.07  | 0.76  | -1.79  | -1.33  | -0.06     | 1.18      | 1.65      |
| spei12   | 2726540      | 74.34 | 0.00   | -5.83  | 5.78   | -0.08  | 0.90  | -2.00  | -1.56  | -0.08     | 1.43      | 1.97      |
| subswc   | 10627200     | 0.00  | 0.00   | 0.00   | 0.76   | 0.09   | 0.14  | 0.00   | 0.00   | 0.00      | 0.37      | 0.45      |
| tp       | 10627200     | 0.00  | 0.00   | 0.00   | 0.80   | 0.03   | 0.03  | 0.00   | 0.00   | 0.02      | 0.08      | 0.12      |
| spei02   | 2726541      | 74.34 | 0.00   | -3.38  | 2.60   | -0.06  | 0.54  | -1.39  | -0.96  | -0.04     | 0.81      | 1.16      |
| pev      | 10627200     | 0.00  | 0.00   | -0.11  | 0.01   | -0.01  | 0.02  | -0.08  | -0.05  | -0.00     | 0.00      | 0.00      |
| tcc      | 10627200     | 0.00  | 0.00   | 0.07   | 0.98   | 0.67   | 0.17  | 0.19   | 0.36   | 0.70      | 0.92      | 0.95      |
| ssrd     | 10627200     | 0.00  | 0.00   | -      | -      | -      | -     | -      | -      | 156202784 | 263067808 | 281347936 |
| u10      | 10627200     | 0.00  | 0.00   | -13.15 | 10.51  | -0.05  | 3.53  | -7.61  | -6.27  | 0.06      | 6.37      | 8.11      |
| spei09   | 2726541      | 74.34 | 0.00   | -4.86  | 5.87   | -0.08  | 0.85  | -1.92  | -1.47  | -0.07     | 1.32      | 1.84      |
| spei24   | 2726481      | 74.34 | 0.00   | -6.39  | 5.91   | -0.09  | 0.99  | -2.13  | -1.68  | -0.10     | 1.56      | 2.11      |
| vpd      | 10627200     | 0.00  | 0.00   | 0.00   | 4.27   | 0.43   | 0.48  | 0.00   | 0.01   | 0.30      | 1.19      | 2.66      |
| swvl2    | 10627200     | 0.00  | 0.00   | 0.00   | 0.76   | 0.09   | 0.14  | 0.00   | 0.00   | 0.00      | 0.37      | 0.45      |
| t2m      | 10627199     | 0.00  | 0.00   | 217.84 | 307.37 | 278.59 | 19.80 | 224.31 | 234.14 | 282.48    | 300.17    | 300.99    |

### Anomalias
    
| variable       | valid_pixels | nan % | zero % | min     | max    | mean  | std  | p01    | p05   | p50   | p95  | p99   |
|:--------------:|:------------:|:-----:|:------:|:-------:|:------:|:-----:|:----:|:------:|:-----:|:-----:|:----:|:-----:|
| wind_anomaly   | 2688452      | 74.70 | 0.00   | -2.26   | 2.20   | 0.00  | 0.20 | -0.53  | -0.31 | -0.00 | 0.32 | 0.55  |
| lai_anomaly    | 2688452      | 74.70 | 1.21   | -248.29 | 244.60 | -0.00 | 4.22 | -11.98 | -4.64 | -0.01 | 5.01 | 11.54 |
| spei01_anomaly | 462398       | 95.65 | 0.00   | -2.14   | 2.45   | 0.00  | 0.43 | -1.09  | -0.72 | 0.01  | 0.69 | 1.13  |
| d2m_anomaly    | 2688452      | 74.70 | 0.00   | -5.70   | 6.32   | -0.00 | 0.94 | -2.46  | -1.58 | 0.00  | 1.52 | 2.49  |
| swvl3_anomaly  | 2688452      | 74.70 | 0.00   | -0.28   | 0.29   | 0.00  | 0.02 | -0.07  | -0.04 | 0.00  | 0.04 | 0.06  |
| spei03_anomaly | 462398       | 95.65 | 0.00   | -3.02   | 3.33   | -0.00 | 0.60 | -1.44  | -0.98 | 0.01  | 0.97 | 1.51  |
| v10_anomaly    | 2688452      | 74.70 | 0.00   | -2.56   | 2.66   | 0.00  | 0.20 | -0.59  | -0.32 | 0.00  | 0.32 | 0.54  |
| swvl1_anomaly  | 2688452      | 74.70 | 0.00   | -0.29   | 0.26   | 0.00  | 0.02 | -0.05  | -0.03 | 0.00  | 0.03 | 0.04  |
| spei06_anomaly | 462398       | 95.65 | 0.00   | -3.56   | 3.69   | 0.00  | 0.73 | -1.68  | -1.18 | 0.00  | 1.22 | 1.80  |
| spei12_anomaly | 462398       | 95.65 | 0.00   | -5.66   | 4.94   | 0.00  | 0.89 | -1.94  | -1.41 | -0.00 | 1.52 | 2.15  |
| subswc_anomaly | 2688452      | 74.70 | 0.00   | -0.27   | 0.26   | 0.00  | 0.02 | -0.06  | -0.04 | 0.00  | 0.03 | 0.06  |
| tp_anomaly     | 2688452      | 74.70 | 0.00   | -0.24   | 0.39   | 0.00  | 0.01 | -0.02  | -0.01 | -0.00 | 0.01 | 0.02  |
| spei02_anomaly | 462398       | 95.65 | 0.00   | -2.57   | 2.92   | -0.00 | 0.53 | -1.30  | -0.88 | 0.01  | 0.86 | 1.36  |
| pev_anomaly    | 2688452      | 74.70 | 0.00   | -0.02   | 0.02   | 0.00  | 0.00 | -0.01  | -0.00 | 0.00  | 0.00 | 0.01  |
| tcc_anomaly    | 2688452      | 74.70 | 0.00   | -0.20   | 0.19   | 0.00  | 0.03 | -0.07  | -0.05 | 0.00  | 0.05 | 0.07  |
| ssrd_anomaly   | 2688452      | 74.70 | 0.00   | -       | -      | -1.73 | -    | -      | -     | -     | -    | -     |
| u10_anomaly    | 2688452      | 74.70 | 0.00   | -3.14   | 3.35   | -0.00 | 0.24 | -0.73  | -0.38 | 0.00  | 0.37 | 0.67  |
| spei09_anomaly | 462398       | 95.65 | 0.00   | -4.35   | 4.65   | 0.00  | 0.83 | -1.83  | -1.32 | -0.00 | 1.41 | 2.02  |
| spei24_anomaly | 462384       | 95.65 | 0.00   | -6.12   | 6.19   | 0.00  | 0.94 | -2.04  | -1.50 | -0.01 | 1.59 | 2.24  |
| vpd_anomaly    | 2688452      | 74.70 | 0.00   | -0.82   | 0.81   | 0.00  | 0.08 | -0.25  | -0.13 | -0.00 | 0.14 | 0.27  |
| swvl2_anomaly  | 2688452      | 74.70 | 0.00   | -0.28   | 0.28   | -0.00 | 0.02 | -0.06  | -0.03 | 0.00  | 0.03 | 0.05  |
| t2m_anomaly    | 2688452      | 74.70 | 0.00   | -5.65   | 6.31   | -0.00 | 0.89 | -2.44  | -1.49 | 0.01  | 1.41 | 2.38  |

# Correlación
## Correlacion global (todo tiempo × espacio)

Usando todos los años (1982–2022) y todos los píxeles válidos (máscara LAI), se hizo una correlación “a lo bruto” concatenando dimensiones tiempo y espacio (N ≈ 62.768 × 41).

|         |   d2m |   pev | swc_sub | swvl1 | swvl2 | swvl3 |   t2m |    tp |   vpd |  ssrd |   lai |   tcc |
|---------|------:|------:|--------:|------:|------:|------:|------:|------:|------:|------:|------:|------:|
| d2m     |     1 |  -0.4 |   -0.03 | -0.06 | -0.04 | -0.03 |  0.90 |  0.53 |  0.33 |  0.58 |  0.52 | -0.17 |
| pev     |  -0.4 |     1 |    0.03 |  0.13 |  0.06 |  0.02 | -0.55 |  0.06 | -0.53 | -0.57 |  0.14 |  0.47 |
| swc_sub | -0.03 |  0.03 |       1 |  0.97 |  0.99 |  0.99 | -0.25 |  0.35 |  -0.5 | -0.41 |  0.42 |  0.54 |
| swvl1   | -0.06 |  0.13 |    0.97 |     1 |  0.98 |  0.96 | -0.31 |  0.37 | -0.56 | -0.49 |  0.45 |  0.62 |
| swvl2   | -0.04 |  0.06 |    0.99 |  0.98 |     1 |  0.98 | -0.27 |  0.35 | -0.50 | -0.43 |  0.42 |  0.55 |
| swvl3   | -0.03 |  0.02 |    0.99 |  0.96 |  0.98 |     1 | -0.25 |  0.35 | -0.49 |  -0.4 |  0.41 |  0.53 |
| t2m     |  0.90 | -0.55 |   -0.25 | -0.31 | -0.27 |  -0.2 |     1 |  0.27 |  0.69 |  0.82 |  0.25 | -0.51 |
| tp      |  0.53 |  0.06 |    0.35 |  0.37 |  0.35 |  0.35 |  0.27 |     1 | -0.28 | -0.03 |  0.73 |  0.47 |
| vpd     |  0.33 | -0.53 |    -0.5 | -0.56 | -0.50 | -0.49 |  0.69 | -0.28 |     1 |  0.78 | -0.30 | -0.79 |
| ssrd    |  0.58 | -0.57 |   -0.41 | -0.49 | -0.43 |  -0.4 |  0.82 | -0.03 | 0.778 |     1 | -0.08 | -0.77 |
| lai     |  0.52 |  0.14 |    0.42 |  0.45 |  0.42 |  0.41 |  0.25 |  0.73 | -0.30 | -0.08 |     1 |  0.48 |
| tcc     | -0.17 |  0.47 |    0.54 |  0.62 |  0.55 |  0.53 | -0.51 |  0.47 | -0.79 | -0.77 |  0.48 |     1 |

- Los **cuatro campos de humedad de suelo** (`swc_sub`, `swvl1`, `swvl2`, `swvl3`) están **muy correlacionados entre sí** (>0.96).  →Redundantes; para un modelo se puede usar 1–2 como máximo.

- `t2m` y `d2m` están **muy correlacionados** (r ≈ 0.90).  

- `t2m` y `ssrd` también están muy correlacionados (r ≈ 0.82), así como `vpd` con `t2m` y `ssrd`.  
  → Variables ligadas a la **energía / calor / déficit hídrico**.

- `lai` presenta correlaciones notables con:
  - `tp` (precipitación) r ≈ **0.73**
  - `tcc` (nubosidad) r ≈ **0.48**
  - `t2m` (temperatura) r ≈ **0.25**
  - `d2m` r ≈ **0.52**
  - Humedad de suelo r ≈ **0.41–0.45**

- `vpd` y `ssrd` están **negativamente correlacionadas con LAI** de forma global (≈ -0.30 y -0.08, respectivamente) - A mayor estrés evaporativo, menor biomasa/vegetación media.

## Correlaciones por año

Para cada año (1982–2022) se recalculó la misma matriz de correlación, restringida a la máscara de LAI. Después se calcularon estadísticas temporales (media, desviación estándar, mínimo y máximo) de cada entrada.
- La media temporal de las matrices anuales es prácticamente idéntica a la matriz global anterior (las diferencias son de orden 0.001–0.01)
- La desviación estándar (std) de los coeficientes de correlación a lo largo de los 41 años es pequeña en casi todos los casos (≈ 0.005–0.02)
- relaciones estadístico-climáticas entre variables son **muy estables en el tiempo**

## Correlaciones temporales pixel a pixel (mapas de correlacion)

Se calculó, para cada variable X y para cada píxel global, la correlación temporal. Esto produce **mapas globales de r**. Relacion local entre series temporales.

- d2m vs lai

![d2m vs lai](/home/dani/Documentos/garciadd/profecia/imagenes/d2m_vs_lai.png "d2m vs lai")
- pev vs lai

![pev vs lai](/home/dani/Documentos/garciadd/profecia/imagenes/pev_vs_lai.png "pev vs lai")

- sub_swc vs lai

![sub_swc vs lai](/home/dani/Documentos/garciadd/profecia/imagenes/sub_swc_vs_lai.png "sub_swc vs lai")

- t2m vs lai

![t2m vs lai](/home/dani/Documentos/garciadd/profecia/imagenes/t2m_vs_lai.png "t2m vs lai")

- tp vs lai

![tp vs lai](/home/dani/Documentos/garciadd/profecia/imagenes/tp_vs_lai.png "tp vs lai")

- vpd vs lai

![vpd vs lai](/home/dani/Documentos/garciadd/profecia/imagenes/vpd_vs_lai.png "vpd vs lai")

- ssrd vs lai

![ssrd vs lai](/home/dani/Documentos/garciadd/profecia/imagenes/ssrd_vs_lai.png "ssrd vs lai")

- tcc vs lai

![tcc vs lai](/home/dani/Documentos/garciadd/profecia/imagenes/tcc_vs_lai.png "tcc vs lai")

- En muchas zonas tropicales y templadas húmedas, LAI correlaciona positivamente con **precipitación** y **humedad de suelo**.
- En zonas semiáridas y desérticas se ven “hot spots” donde pequeñas variaciones de lluvia producen grandes cambios en LAI.
- En regiones boreales, la correlación con **temperatura** es muy marcada y espacialmente coherente.
- `vpd` y `ssrd` muestran patrones negativos con LAI allí donde el estrés hídrico es crítico.

# Clustering climatico (tipos de clima)
## Construcción del dataset para clustering

Para cada píxel global y para todo el periodo 1982–2022:

1. Se extrajeron las series temporales anuales de todas las variables climáticas seleccionadas.
2. Se construyó un vector de características por píxel (combinando dimensiones tiempo × variable).
3. Se aplicó un **escalado estándar** (`StandardScaler`).
4. Se redujo la dimensionalidad con **PCA (2 componentes)**:
   - Varianza explicada ≈ **35 %** por PC1 y **29 %** por PC2.
5. El clustering se realizó en el espacio PCA para tener estructuras más limpias.

Se utilizo la mascara de tierra calculada con el indice LAI
- Píxeles totales globales: 259.200  
- Píxeles válidos tras intersección de máscaras: **62.768**

## KNN / KMeans y número de clusters

Se probaron distintos valores de k para KMeans (con y sin PCA):
- variables utilizadas = ["t2m", "tp", "vpd", "ssrd", "swvl2", "lai", "tcc"]
- Mapa final de clusters (KNN con k=5)

![knn clustering (k=5)](/home/dani/Documentos/garciadd/profecia/imagenes/clustering_knn.png "knn clustering (k=5)")

## Interpretación cualitativa de los clusters

Tras revisar cada cluster se asignaron etiquetas climáticas aproximadas:

- **Cluster 0 → “templado”**  
  - Europa occidental, Mediterráneo, parte de Estados Unidos, Chile central, sur de Australia...
- **Cluster 1 → “tropical”**  
  - Amazonia, Congo, Sudeste asiático, Indonesia, Papúa...
- **Cluster 2 → “boreal”**  
  - Alaska, Canadá boreal, Siberia, norte de Escandinavia...
- **Cluster 3 → “desértico / semiárido cálido”**  
  - Sahara, Arabia, Australia interior, parte de Namibia/Botswana...
- **Cluster 4 → “árido / estepario templado”**  
  - Patagonia, zonas de transición áridas, cuencas interiores…

A partir de las etiquetas de cluster se generó, para cada clima, una máscara 2D.

## Correlación por tipo de clima
Nos centramos en **cómo cambia la correlación entre LAI y el resto de variables según el clima**

### clima tropical

|     |   d2m |   pev |   swc_sub |   swvl1 |   swvl2 |   swvl3 |   t2m |    tp |    vpd |   ssrd |   lai |   tcc |
|:----|------:|------:|----------:|--------:|--------:|--------:|------:|------:|-------:|-------:|------:|------:|
| lai |  0.42 | 0.262 |     0.103 |    0.12 |   0.107 |   0.101 | 0.366 | 0.094 | -0.081 |  0.282 |     1 | 0.334 |

- LAI correlaciona de forma **moderada** con `d2m` y `t2m` (0.37–0.42).
- Relación positiva con `tp` (0.09) - más débil de lo esperado 
- LAI aumenta con `tcc` (0.33) y con `ssrd` (0.28) 
- `vpd` está muy débilmente correlacionado y con signo negativo (-0.08)

En regiones tropicales la lluvia deja de ser factor limitante (siempre “alta”) y pasa a tener mas relacion con la temperatura y la radiacion¿?

### clima desértico

|     |   d2m |    pev |   swc_sub |   swvl1 |   swvl2 |   swvl3 |   t2m |    tp |    vpd |   ssrd |   lai |   tcc |
|:----|------:|-------:|----------:|--------:|--------:|--------:|------:|------:|-------:|-------:|------:|------:|
| lai | 0.372 | -0.499 |     0.548 |   0.699 |    0.53 |   0.543 |  0.04 | 0.803 | -0.273 |  -0.22 |     1 | 0.571 |

- LAI se relaciona fuertemente con:
  - `tp` (0.80)
  - `swvl1/swvl2/swc_sub` (0.53–0.70)
  - `tcc` (0.57)
  - `pev` está fuertemente anticorrelado con LAI (-0.50). 

En desiertos, la limitación de agua manda, mas correlacion con tp

### clima templado

|     |   d2m |   pev |   swc_sub |   swvl1 |   swvl2 |   swvl3 |   t2m |    tp |    vpd |   ssrd |   lai |   tcc |
|:----|------:|------:|----------:|--------:|--------:|--------:|------:|------:|-------:|-------:|------:|------:|
| lai | 0.402 | 0.198 |      0.22 |   0.347 |   0.274 |   0.202 | 0.185 | 0.638 | -0.328 |  -0.44 |     1 |  0.39 |

- Correlación fuerte de LAI con:
  - `tp` (0.64)
  - `tcc` (0.39)
  - humedad de suelo (0.20–0.27)
  - `vpd` y `ssrd` negativos con LAI (-0.33 y -0.44).  

En climas templados, los años más radiativos/estresantes en agua tienden a **reducir** el LAI, sobre todo si viene acompañado de déficit hídrico.

### clima árido

|     |   d2m |   pev |   swc_sub |   swvl1 |   swvl2 |   swvl3 |   t2m |    tp |    vpd |   ssrd |   lai |   tcc |
|:----|------:|------:|----------:|--------:|--------:|--------:|------:|------:|-------:|-------:|------:|------:|
| lai | 0.249 |  0.34 |     0.208 |   0.297 |   0.235 |     0.2 |  0.03 | 0.405 | -0.339 | -0.291 |     1 | 0.463 |

- LAI responde a:
  - `tp` (0.41)
  - `tcc` (0.46)
  - humedad de suelo (0.20–0.30)
  - `vpd` y `ssrd` otra vez negativos (~ -0.34, -0.29).  

Coherencia con el caso templado: variaciones en agua disponible explican gran parte de la variabilidad de LAI.

### clima boreal

|     |   d2m |    pev |   swc_sub |   swvl1 |   swvl2 |   swvl3 |   t2m |    tp |   vpd |   ssrd |   lai |    tcc |
|:----|------:|-------:|----------:|--------:|--------:|--------:|------:|------:|------:|-------:|------:|-------:|
| lai | 0.532 | -0.181 |       0.2 |   0.197 |   0.196 |   0.201 | 0.559 | 0.327 | 0.519 |  0.213 |     1 | -0.292 |

- LAI muy ligado a:
  - `t2m` (0.56) y `d2m` (0.53)
  - `tp` (0.33)
  - `vpd` (0.52)
  - `tcc` anticorrelacionado con LAI (-0.29): en boreal, más nubosidad puede significar menos radiación disponible para crecer.

En altas latitudes, la limitación principal es la **temperatura / longitud de la estación de crecimiento**, más que el agua (aunque esta también cuenta).

# Modelización de LAI
## Variables redundantes

- `swc_sub`, `swvl1`, `swvl2`, `swvl3` → extremadamente colineales.
- `t2m` y `d2m` → muy correlacionadas globalmente.

Para evitar multicolinealidad fuerte y sobreajuste, se recomienda:

- Quedarse con **1–2 variables de humedad de suelo** (por ejemplo `swvl2` + `swc_sub`).
- Mantener **t2m** como temperatura principal, y valorar si `d2m` aporta algo extra localmente.
- O bien usar PCA también en el subespacio de humedad de suelo.

## Variables clave para explicar LAI

A la luz de las correlaciones globales, por clima y pixelwise:

- **Agua / humedad**
  - `tp`, `swvl2`, `swc_sub`, `pev` (signo contrario)  
  - Especialmente importantes en **climas áridos, desérticos y templados**.

- **Temperatura / energía**
  - `t2m`, `ssrd`, `vpd`  
  - Dominantes en **climas boreales**.

- **Nubes / radiación efectiva**
  - `tcc` modula la radiación, con signo positivo en climas húmedos (más nubes = menos estrés) y negativo en climas boreales (más nubes = menos energía para crecer).

## Conjunto de variables para el modelo

Como conjunto compacto de predictores de LAI anual:

- `t2m` – Temperatura media anual
- `tp` – Precipitación total anual
- `vpd` – Déficit de presión de vapor medio (estrés hídrico)
- `ssrd` – Radiación total en superficie
- `swvl2` – Humedad de suelo a capa intermedia
- `tcc` – Nubosidad total
- (Opcional) `pev` – Evapotranspiración potencial (para detectar años de alta demanda hídrica)