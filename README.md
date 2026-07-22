---

title: ROTAIA
emoji: 🚚
colorFrom: blue
colorTo: blue
sdk: streamlit
app_file: app.py
pinned: false
---

https://github.com/user-attachments/assets/5e836050-e9a6-4b5a-a1d3-e653f28d6ee3

# rotaIA 🚚

O **rotaIA** nasceu como o produto final do meu Trabalho de Conclusão de Curso (TCC) no MBA em Data Science e Analytics da ESALQ-USP. Durante as minhas pesquisas, percebi que os modelos puros de Machine Learning sofriam muito com problemas de convergência computacional quando o volume de entregas subia demais. Para resolver esse gargalo, desenvolvi um modelo híbrido e, a partir dessa inteligência, criei esta aplicação para resolver o clássico Travelling Salesman Problem (Problema do Caixeiro Viajante) de forma visual e prática.

A ideia aqui é entregar uma aplicação de roteirização robusta e completa: o usuário consegue simular rotas inteiras em segundos, cruzar coordenadas geográficas complexas e exportar a rota final otimizada direto na interface.

### Tecnologias e Conceitos Aplicados
* **Modelo Híbrido (KMeans + RL):** O arranjo mais eficiente do meu estudo para cenários onde a rota não precisa retornar à origem. Ele separa as entregas em clusters, faz melhor rota ENTRE CLUSTERS e por fim roteiriza as entregas INTRA CLUSTERS, quebrando aquela tendência formato de "arco".
* **Modelo Heurístico (Savings + VND):** A escolha perfeita para quando a rota obrigatoriamente precisa voltar ao ponto de partida (depósito). Ele calcula a economia marginal de distância analiticamente e fecha circuitos perfeitos de forma instantânea.
* **Validação via OSRM:** Toda a inteligência por trás da aplicação é validada via OSRM, calculando as distâncias com base na malha rodoviária real das ruas (e não em linha reta).
* **Solução para o Travelling Salesman Problem (Problema do Caixeiro Viajante):** Motores algorítmicos que o usuário pode alternar no painel para resolver o problema de forma visual e prática.

### Contexto
Este projeto foi desenvolvido como o produto final do meu Trabalho de Conclusão de Curso (TCC) no MBA em Data Science e Analytics da **ESALQ-USP**, transformando modelos matemáticos complexos em uma ferramenta intuitiva para quem precisa planejar rotas eficientes no dia a dia.

---
**Desenvolvido por Hugo Rocha** [LinkedIn](https://www.linkedin.com/in/hugogrocha) | [GitHub](https://github.com/hugogr99)
