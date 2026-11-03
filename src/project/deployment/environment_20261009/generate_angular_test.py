from pathlib import Path
P=Path(__file__).resolve().parent
s=(P/'test_spatial_exclusion.py').read_text()
a=s.index('source=source.replace(');b=s.index("(P/'music_spatial_candidate.cpp')",a)
replacement="""source=source.replace('''        if (evaluate)
            value = score_core(request[0], request[1], request[2], speed);''','''        if (evaluate) {
            value = score_core(request[0], request[1], request[2], speed);
            if(state!=14 && value<1e19f) {
                for(int old=0;old<target;old++) {
                    float dot=0;
                    for(int c=0;c<3;c++)dot+=scored_direction[c]*previous[old][c];
                    if(dot>.9781476007f)value=1e20f;
                }
            }
        }''')
"""
s=s[:a]+replacement+s[b:]
s=s.replace('music_spatial_candidate','music_angular_candidate').replace('music_spatial_bridge','music_angular_bridge').replace('music_spatial.dll','music_angular.dll').replace('spatial_exclusion_comparison.json','angular_exclusion_comparison.json')
(P/'test_angular_exclusion.py').write_text(s)
