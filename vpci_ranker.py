# ═══════════════════════════════════════════════════════════════════════════════
# UPDATED tab5 BLOCK — shows ALL ranked stocks (not just top 10)
# ═══════════════════════════════════════════════════════════════════════════════
# Replace your entire `with tab5:` block with the code below.
# Indentation: 12 spaces for `with tab5:` and 16 spaces for the body
# (matching `with tab4:` exactly in your app.py).
# ═══════════════════════════════════════════════════════════════════════════════

            with tab5:
                st.subheader("All Ranked Buyable Candidates")
                st.caption("Composite score: VPCI 25% + RS 25% + 52wH 20% + Tight base 15% + Volume 10% + Mcap fit 5%")

                try:
                    ranked = rank_stocks(df_sorted, include_relaxed=False)
                except Exception as e:
                    st.error(f"Ranker error: {e}")
                    ranked = pd.DataFrame()

                if len(ranked) > 0:
                    display_cols = [
                        "rank", "symbol", "close", "composite_score",
                        "score_vpci", "score_rs", "score_52w",
                        "score_tight", "score_vol", "score_mcap", "status"
                    ]
                    display_cols = [c for c in display_cols if c in ranked.columns]

                    # Show ALL ranked stocks (no .head() limit)
                    st.dataframe(
                        ranked[display_cols].style.format({
                            "composite_score": "{:.3f}",
                            "score_vpci": "{:.2f}",
                            "score_rs": "{:.2f}",
                            "score_52w": "{:.2f}",
                            "score_tight": "{:.2f}",
                            "score_vol": "{:.2f}",
                            "score_mcap": "{:.2f}",
                            "close": "{:.2f}",
                        }),
                        use_container_width=True,
                        hide_index=True
                    )

                    st.info(
                        f"Total ranked: {len(ranked)} stocks. "
                        f"Top 5 typically have score > 0.80. "
                        f"Score gap from #1 to #5 indicates conviction strength."
                    )

                    # Download button for ranked CSV
                    ranked_csv = ranked[display_cols].to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Download Ranked CSV",
                        data=ranked_csv,
                        file_name=f"vpci_ranked_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                        key="ranked_download"
                    )
                else:
                    st.warning("No 7/7 stocks to rank this week. Try the Watchlist tab for 6/7 candidates.")
